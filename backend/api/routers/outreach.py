"""
outreach.py
-----------
Outreach control endpoints:
  POST /users/me/outreach-settings                     configure Resend + Cal.com
  GET  /users/me/outreach-settings                     get current settings
  POST /outreach/{campaign_id}/leads/{lead_id}/send    send Email 1 to a lead
  GET  /outreach/{campaign_id}/schedule                view follow-up schedule
  POST /outreach/{campaign_id}/leads/{lead_id}/pause   manually pause a lead
  POST /outreach/{campaign_id}/leads/{lead_id}/resume  manually resume a paused lead
  GET  /outreach/review                                list leads flagged for human review
  POST /outreach/review/{lead_id}/decision             submit human decision on a flagged reply
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field

from backend.api.dependencies.auth import (
    get_current_user,
    require_active_subscription,
    verify_campaign_ownership,
)
from backend.infrastructure.factory import get_db
from backend.core.enums import LeadStatus
from backend.core.outreach.sender import (
    SendEmailInput, send_outreach_email,
    get_outreach_settings, _cancel_followups,
    _pause_followups, _resume_followups, _now_iso,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Outreach"])



# REQUEST / RESPONSE MODELS


class OutreachSettingsRequest(BaseModel):
    resend_api_key: str = Field(..., description="User's Resend API key (re_...).")
    sending_domain: str = Field(..., description="Verified sending domain in Resend e.g. 'company.com'.")
    sending_email: str = Field(..., description="From email address e.g. 'john@company.com'.")
    sending_name: str = Field(..., description="From display name e.g. 'John from Acme'.")
    cal_link: Optional[str] = Field(None, description="Cal.com booking link to embed in interested replies.")


class OutreachSettingsResponse(BaseModel):
    user_id: str
    sending_domain: Optional[str]
    sending_email: Optional[str]
    sending_name: Optional[str]
    cal_link: Optional[str]
    is_configured: bool
    has_api_key: bool       # never return the actual key


class SendEmailRequest(BaseModel):
    email_number: int = Field(
        1, ge=1, le=3,
        description="Which email to send: 1 (initial), 2 (follow-up), or 3 (final)."
    )


class SendEmailResponse(BaseModel):
    success: bool
    outreach_log_id: str
    resend_message_id: Optional[str]
    followups_scheduled: int
    error: Optional[str]


class FollowUpScheduleItem(BaseModel):
    id: str
    lead_id: str
    lead_name: Optional[str]
    lead_email: Optional[str]
    email_number: int
    scheduled_date: str
    status: str
    paused_until: Optional[str]
    sent_at: Optional[str]


class ScheduleResponse(BaseModel):
    campaign_id: str
    schedule: List[FollowUpScheduleItem]
    total: int


class ReviewDecisionRequest(BaseModel):
    decision: Literal["reply", "close", "do_not_contact", "ignore"] = Field(
        ...,
        description=(
            "'reply' = send the drafted response to the lead. "
            "'close' = close the thread, mark Inactive. "
            "'do_not_contact' = mark Do Not Contact. "
            "'ignore' = dismiss the flag, return lead to Active."
        )
    )
    custom_response: Optional[str] = Field(
        None,
        description="Optional custom response body. If not set, uses the agent's drafted response."
    )


class ReviewDecisionResponse(BaseModel):
    lead_id: str
    decision: str
    action_taken: str
    response_sent: bool



# OUTREACH SETTINGS


@router.get("/users/me/outreach-settings", response_model=OutreachSettingsResponse)
async def get_my_outreach_settings(user: Dict = Depends(get_current_user)):
    """Get the current user's outreach configuration."""
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM user_outreach_settings WHERE user_id = ?", (user["id"],)
    ).fetchone()
    conn.close()

    if not row:
        return OutreachSettingsResponse(
            user_id=user["id"],
            sending_domain=None,
            sending_email=None,
            sending_name=None,
            cal_link=None,
            is_configured=False,
            has_api_key=False,
        )

    r = dict(row)
    return OutreachSettingsResponse(
        user_id=user["id"],
        sending_domain=r.get("sending_domain"),
        sending_email=r.get("sending_email"),
        sending_name=r.get("sending_name"),
        cal_link=r.get("cal_link"),
        is_configured=bool(r.get("is_configured")),
        has_api_key=bool(r.get("resend_api_key")),
    )


@router.put("/users/me/outreach-settings", response_model=OutreachSettingsResponse)
async def update_outreach_settings(
    body: OutreachSettingsRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Save or update the user's outreach configuration.
    Must be set before any emails can be sent.
    The Resend API key is stored but never returned in GET responses.
    """
    db = get_db()
    now = _now_iso()
    is_configured = all([
        body.resend_api_key,
        body.sending_domain,
        body.sending_email,
        body.sending_name,
    ])

    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT id FROM user_outreach_settings WHERE user_id = ?", (user["id"],)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE user_outreach_settings
               SET resend_api_key=?, sending_domain=?, sending_email=?,
                   sending_name=?, cal_link=?, is_configured=?, updated_at=?
               WHERE user_id=?""",
            (body.resend_api_key, body.sending_domain, body.sending_email,
             body.sending_name, body.cal_link, 1 if is_configured else 0,
             now, user["id"])
        )
    else:
        import uuid
        conn.execute(
            """INSERT INTO user_outreach_settings
               (id, user_id, resend_api_key, sending_domain, sending_email,
                sending_name, cal_link, is_configured, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), user["id"], body.resend_api_key,
             body.sending_domain, body.sending_email, body.sending_name,
             body.cal_link, 1 if is_configured else 0, now, now)
        )

    conn.commit()
    conn.close()

    logger.info(f"[Outreach] Updated outreach settings for user {user['id'][:8]}")

    return OutreachSettingsResponse(
        user_id=user["id"],
        sending_domain=body.sending_domain,
        sending_email=body.sending_email,
        sending_name=body.sending_name,
        cal_link=body.cal_link,
        is_configured=is_configured,
        has_api_key=True,
    )



# SEND EMAIL


@router.post(
    "/outreach/{campaign_id}/leads/{lead_id}/send",
    response_model=SendEmailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_email(
    campaign_id: str,
    lead_id: str,
    body: SendEmailRequest,
    background_tasks: BackgroundTasks,
    user: Dict = Depends(require_active_subscription),
):
    """
    Trigger sending an email in the outreach sequence to a specific lead.
    Typically called after the user reviews the generated email sequences.

    Email 1 → marks lead Active, schedules Email 2 (day 3) and Email 3 (day 7).
    Email 2/3 → sent by the scheduler automatically, but can be triggered manually here.

    Returns 202 Accepted — send happens in background.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    # Verify lead belongs to campaign
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    lead = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND campaign_id = ?",
        (lead_id, campaign_id)
    ).fetchone()
    conn.close()

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found in campaign {campaign_id}."
        )
    lead = dict(lead)

    # Verify outreach settings configured
    outreach_settings = get_outreach_settings(user["id"])
    if not outreach_settings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Outreach not configured. "
                "Set your Resend API key and sending details at PUT /users/me/outreach-settings"
            )
        )

    # Verify email sequence exists
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    sequence = conn.execute(
        "SELECT * FROM email_sequences WHERE lead_id = ? AND campaign_id = ? ORDER BY created_at DESC LIMIT 1",
        (lead_id, campaign_id)
    ).fetchone()
    conn.close()

    if not sequence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No email sequence found. Run the pipeline first to generate email sequences."
        )
    sequence = dict(sequence)

    email_num = body.email_number
    subject = sequence.get(f"email_{email_num}_subject", "")
    body_html = sequence.get(f"email_{email_num}_body", "")

    if not body_html:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email {email_num} body is empty. The sequence may not have been generated yet."
        )

    send_input = SendEmailInput(
        lead_id=lead_id,
        campaign_id=campaign_id,
        user_id=user["id"],
        email_number=email_num,
        to_email=sequence["lead_email"],
        from_email=outreach_settings.sending_email,
        from_name=outreach_settings.sending_name,
        subject=subject,
        body_html=body_html,
        reply_to=outreach_settings.sending_email,
        resend_api_key=outreach_settings.resend_api_key,
    )

    background_tasks.add_task(_send_in_background, send_input)

    return SendEmailResponse(
        success=True,
        outreach_log_id="queued",
        resend_message_id=None,
        followups_scheduled=0,
        error=None,
    )


async def _send_in_background(inp: SendEmailInput):
    try:
        result = await send_outreach_email(inp)
        if result.success:
            logger.info(f"[Outreach] Email {inp.email_number} sent to {inp.to_email}")
        else:
            logger.error(f"[Outreach] Email {inp.email_number} failed: {result.error}")
    except Exception as e:
        logger.error(f"[Outreach] Background send error: {e}")



# SCHEDULE

@router.get(
    "/outreach/{campaign_id}/schedule",
    response_model=ScheduleResponse,
)
async def get_schedule(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """View the follow-up schedule for all leads in a campaign."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT fs.*, l.name as lead_name, l.email as lead_email
           FROM followup_schedule fs
           LEFT JOIN leads l ON fs.lead_id = l.id
           WHERE fs.campaign_id = ?
           ORDER BY fs.scheduled_date ASC""",
        (campaign_id,)
    ).fetchall()
    conn.close()

    items = [
        FollowUpScheduleItem(
            id=r["id"],
            lead_id=r["lead_id"],
            lead_name=r.get("lead_name"),
            lead_email=r.get("lead_email"),
            email_number=r["email_number"],
            scheduled_date=r["scheduled_date"],
            status=r["status"],
            paused_until=r.get("paused_until"),
            sent_at=r.get("sent_at"),
        )
        for r in [dict(row) for row in rows]
    ]

    return ScheduleResponse(campaign_id=campaign_id, schedule=items, total=len(items))



# PAUSE / RESUME


@router.post("/outreach/{campaign_id}/leads/{lead_id}/pause")
async def pause_lead(
    campaign_id: str,
    lead_id: str,
    user: Dict = Depends(get_current_user),
):
    """Manually pause all follow-ups for a lead for 7 days."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    from backend.core.outreach.sender import _date_plus_days
    resume_date = _date_plus_days(7)
    _pause_followups(lead_id, resume_date)
    db.update_lead_status(lead_id, LeadStatus.PAUSED)

    return {"message": f"Lead {lead_id} paused until {resume_date}."}


@router.post("/outreach/{campaign_id}/leads/{lead_id}/resume")
async def resume_lead(
    campaign_id: str,
    lead_id: str,
    user: Dict = Depends(get_current_user),
):
    """Manually resume a paused lead. Continues sequence from where it left off."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    _resume_followups(lead_id)
    db.update_lead_status(lead_id, LeadStatus.ACTIVE)

    return {"message": f"Lead {lead_id} resumed."}



# HUMAN REVIEW


@router.get("/outreach/review")
async def list_review_leads(user: Dict = Depends(get_current_user)):
    """
    List all leads flagged for human review across all campaigns.
    These are leads with ambiguous replies that the AI could not classify.
    """
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT l.id, l.name, l.email, l.company, l.title,
                  l.campaign_id, l.status, l.updated_at,
                  rl.body_text as reply_body,
                  rl.classification as agent_classification,
                  rl.confidence_score,
                  rl.response_body as drafted_response_body,
                  rl.id as reply_log_id
           FROM leads l
           LEFT JOIN reply_log rl ON rl.lead_id = l.id
           WHERE l.user_id = ? AND l.status = ?
           ORDER BY l.updated_at DESC""",
        (user["id"], LeadStatus.OUTREACH_REVIEW)
    ).fetchall()
    conn.close()

    return {"leads": [dict(r) for r in rows], "total": len(rows)}


@router.post(
    "/outreach/review/{lead_id}/decision",
    response_model=ReviewDecisionResponse,
)
async def submit_review_decision(
    lead_id: str,
    body: ReviewDecisionRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Submit a human decision for a lead flagged for review.
    The human reads the reply, chooses an action, and optionally edits the response.
    """
    db = get_db()

    # Verify lead belongs to this user
    lead = None
    leads = db.get_leads_for_campaign.__func__ if False else None
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    lead_row = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND user_id = ?",
        (lead_id, user["id"])
    ).fetchone()

    # Get most recent reply log
    reply_log = conn.execute(
        "SELECT * FROM reply_log WHERE lead_id = ? ORDER BY created_at DESC LIMIT 1",
        (lead_id,)
    ).fetchone()
    conn.close()

    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead = dict(lead_row)
    reply = dict(reply_log) if reply_log else {}

    outreach_settings = get_outreach_settings(user["id"])
    response_sent = False
    action_taken = body.decision

    if body.decision == "reply":
        # Send response
        if outreach_settings and (body.custom_response or reply.get("response_body")):
            response_text = body.custom_response or reply.get("response_body", "")
            try:
                resend_sdk_module = __import__("resend")
                resend_sdk_module.api_key = outreach_settings.resend_api_key
                await resend_sdk_module.Emails.send_async({
                    "from": f"{outreach_settings.sending_name} <{outreach_settings.sending_email}>",
                    "to": [lead["email"]],
                    "subject": f"Re: your reply",
                    "html": response_text.replace("\n", "<br>"),
                    "text": response_text,
                })
                response_sent = True
            except Exception as e:
                logger.error(f"[Outreach] Review reply send failed: {e}")
        db.update_lead_status(lead_id, LeadStatus.REPLIED)
        _cancel_followups(lead_id, "human_replied")

    elif body.decision == "close":
        db.update_lead_status(lead_id, LeadStatus.INACTIVE)
        _cancel_followups(lead_id, "human_closed")

    elif body.decision == "do_not_contact":
        db.update_lead_status(lead_id, LeadStatus.DO_NOT_CONTACT)
        _cancel_followups(lead_id, "human_dnc")

    elif body.decision == "ignore":
        db.update_lead_status(lead_id, LeadStatus.ACTIVE)

    return ReviewDecisionResponse(
        lead_id=lead_id,
        decision=body.decision,
        action_taken=action_taken,
        response_sent=response_sent,
    )
