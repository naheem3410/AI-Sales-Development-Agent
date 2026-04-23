"""
reply_handler.py
----------------
Orchestrates the full reply processing flow.

Called by the Resend inbound webhook after a reply comes in.
Coordinates: reply_agent → action execution → DB updates → outbound send if needed.

Flow:
  1. Match inbound email to a lead via Resend message ID or from-email
  2. Fetch RAG context if lead appears interested (pre-fetch before agent call)
  3. Call reply_agent to classify and draft response
  4. Execute the recommended action
  5. Log everything to reply_log

All actions and their effects:
  reply_with_rag   → send drafted response via Resend, update lead to Replied
  close_thread     → send polite close, mark lead Inactive
  pause_lead       → pause all follow-ups, mark lead Paused
  do_not_contact   → cancel all follow-ups, mark lead Do Not Contact
  create_referral  → create new lead from referral, mark original Transferred
  flag_review      → mark lead OutreachReview, no automated action
"""

import uuid
import sqlite3
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

import resend as resend_sdk
from pydantic import BaseModel, Field

from backend.infrastructure.factory import get_db
from backend.core.enums import LeadStatus
from backend.core.outreach.agents.reply_agent import ReplyAgentInput, ReplyAgentOutput, run_reply_agent
from backend.core.outreach.rag.intelligent_retrieval import retrieve_reply_rag_context
from backend.core.outreach.sender import (
    get_outreach_settings,
    _cancel_followups,
    _pause_followups,
    _now_iso,
)

logger = logging.getLogger(__name__)

OOF_PAUSE_DAYS = 7

# Reply agent context limits (approximate token safety)
MAX_THREAD_CHARS = 28_000
PER_MESSAGE_BODY_CAP = 12_000


def _truncate_block(text: Optional[str], cap: int) -> str:
    if not text or not str(text).strip():
        return "(empty)"
    t = str(text).strip()
    if len(t) <= cap:
        return t
    return t[:cap] + "\n… (truncated)"


def _parse_ts_iso(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _fmt_list(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(str(x) for x in val)
    return str(val)


def _format_icp_markdown(icp: Optional[Dict[str, Any]]) -> Optional[str]:
    if not icp:
        return None
    lines = []
    if icp.get("target_type"):
        lines.append(f"Target type: {icp['target_type']}")
    if icp.get("industry"):
        lines.append(f"Industry: {_fmt_list(icp.get('industry'))}")
    cm, cx = icp.get("company_size_min"), icp.get("company_size_max")
    if cm is not None or cx is not None:
        lines.append(f"Company size: {cm or '?'} — {cx or '?'} employees")
    if icp.get("funding_status"):
        lines.append(f"Funding: {_fmt_list(icp.get('funding_status'))}")
    if icp.get("job_titles"):
        lines.append(f"Job titles: {_fmt_list(icp.get('job_titles'))}")
    if icp.get("seniority"):
        lines.append(f"Seniority: {_fmt_list(icp.get('seniority'))}")
    if icp.get("locations"):
        lines.append(f"Locations: {_fmt_list(icp.get('locations'))}")
    if icp.get("tech_stack"):
        lines.append(f"Tech stack: {_fmt_list(icp.get('tech_stack'))}")
    if icp.get("demographics"):
        lines.append(f"Demographics: {icp['demographics']}")
    if icp.get("confidence_score") is not None:
        lines.append(f"ICP confidence: {icp['confidence_score']}")
    if icp.get("missing_fields"):
        lines.append(f"Missing fields: {_fmt_list(icp.get('missing_fields'))}")
    return "\n".join(lines) if lines else None


def _format_product_brief_extended(brief: Optional[Dict[str, Any]]) -> Optional[str]:
    if not brief:
        return None
    lines = []
    for key, label in (
        ("product_name", "Product"),
        ("what_it_does", "What it does"),
        ("who_it_is_for", "Who it is for"),
        ("pain_it_solves", "Pain it solves"),
        ("ideal_customer_description", "Ideal customer"),
    ):
        v = brief.get(key)
        if v:
            lines.append(f"{label}: {v}")
    kd = brief.get("key_differentiators")
    if kd:
        if isinstance(kd, list):
            lines.append("Key differentiators:\n- " + "\n- ".join(str(x) for x in kd))
        else:
            lines.append(f"Key differentiators: {kd}")
    return "\n".join(lines) if lines else None


def _format_lead_details_markdown(lead: Dict[str, Any]) -> Optional[str]:
    """Extra CRM fields beyond name/email/company/title shown in the prompt header."""
    skip = {
        "id", "campaign_id", "user_id", "name", "email",
        "company", "title", "created_at", "updated_at",
        "last_email_sent",
    }
    lines = []
    for key in (
        "status",
        "email_status",
        "first_name",
        "last_name",
        "seniority",
        "phone",
        "company_size",
        "industry",
        "location",
        "country",
        "linkedin",
        "provider",
        "provider_id",
        "lead_type",
    ):
        if key in skip:
            continue
        v = lead.get(key)
        if v is not None and v != "":
            lines.append(f"{key}: {v}")
    # Include lead id once for debugging / traceability
    lines.insert(0, f"lead_id: {lead.get('id', '')}")
    return "\n".join(lines) if lines else None


def _lookup_original_subject(db_path: str, lead_id: str, email_number: int) -> Optional[str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """SELECT subject FROM outreach_log
               WHERE lead_id = ? AND email_number = ?
               ORDER BY COALESCE(sent_at, created_at) DESC LIMIT 1""",
            (lead_id, email_number),
        ).fetchone()
        return row["subject"] if row else None
    finally:
        conn.close()


def _build_conversation_history(
    db_path: str,
    lead_id: str,
    exclude_resend_inbound_id: Optional[str],
) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        outreach_rows = conn.execute(
            """SELECT * FROM outreach_log WHERE lead_id = ?
               ORDER BY COALESCE(sent_at, created_at) ASC""",
            (lead_id,),
        ).fetchall()
        reply_rows = conn.execute(
            """SELECT * FROM reply_log WHERE lead_id = ?
               ORDER BY received_at ASC""",
            (lead_id,),
        ).fetchall()
    finally:
        conn.close()

    events: List[Tuple[str, str, sqlite3.Row]] = []
    for row in outreach_rows:
        r = dict(row)
        ts = r.get("sent_at") or r.get("created_at") or ""
        events.append((ts, "outbound", row))
    for row in reply_rows:
        r = dict(row)
        if exclude_resend_inbound_id and r.get("resend_inbound_id") == exclude_resend_inbound_id:
            continue
        ts = r.get("received_at") or ""
        events.append((ts, "reply_log", row))

    events.sort(key=lambda x: _parse_ts_iso(x[0]))

    blocks: List[str] = []
    for ts, kind, row in events:
        r = dict(row)
        if kind == "outbound":
            body = _truncate_block(r.get("body_snapshot"), PER_MESSAGE_BODY_CAP)
            blocks.append(
                "\n".join(
                    [
                        f"--- Outbound (sequence email {r.get('email_number', '?')}) ---",
                        f"At: {r.get('sent_at') or r.get('created_at')}",
                        f"Subject: {r.get('subject') or '(no subject)'}",
                        f"From: {r.get('from_email')} → To: {r.get('to_email')}",
                        f"Status: {r.get('status')}",
                        "",
                        body,
                    ]
                )
            )
        else:
            body_in = _truncate_block(r.get("body_text"), PER_MESSAGE_BODY_CAP)
            blocks.append(
                "\n".join(
                    [
                        f"--- Lead inbound (logged) ---",
                        f"Received: {r.get('received_at')}",
                        f"Subject: {r.get('subject') or '(no subject)'}",
                        f"From: {r.get('from_email') or '(unknown)'}",
                        "",
                        body_in,
                    ]
                )
            )
            if r.get("response_sent") and r.get("response_body"):
                blocks.append(
                    "--- Our automated reply (after that inbound) ---\n"
                    + _truncate_block(r.get("response_body"), PER_MESSAGE_BODY_CAP)
                )

    text = "\n\n".join(blocks)
    if len(text) > MAX_THREAD_CHARS:
        text = "(Earlier thread truncated for length.)\n\n" + text[-MAX_THREAD_CHARS:]
    return text if text.strip() else "(No prior outreach or logged replies for this lead.)"


# INPUT / OUTPUT MODELS

class InboundReplyEvent(BaseModel):
    """
    Parsed inbound email event from Resend webhook.
    Maps directly from the Resend email.received payload.
    """

    resend_inbound_id: str = Field(
        ..., description="Resend's ID for this inbound email."
    )
    from_email: str = Field(
        ..., description="Email address of the person who replied."
    )
    from_name: Optional[str] = Field(
        None, description="Display name of the person who replied."
    )
    to_email: str = Field(
        ..., description="The address the reply was sent to (your sending address)."
    )
    subject: Optional[str] = Field(
        None, description="Subject line of the inbound reply."
    )
    body_text: str = Field(
        ..., description="Plain text body of the inbound reply."
    )
    body_html: Optional[str] = Field(
        None, description="HTML body of the inbound reply."
    )
    in_reply_to: Optional[str] = Field(
        None,
        description=(
            "Resend message ID of the original outbound email. "
            "Used to match the reply back to the correct lead."
        )
    )


class ReplyHandlerOutput(BaseModel):
    """Result of processing an inbound reply."""

    lead_id: Optional[str] = Field(
        None, description="Lead ID that was matched to this reply."
    )
    lead_matched: bool = Field(
        ..., description="Whether the reply was matched to a known lead."
    )
    classification: Optional[str] = Field(
        None, description="Intent classification from the reply agent."
    )
    action_taken: Optional[str] = Field(
        None, description="The action that was executed."
    )
    response_sent: bool = Field(
        False, description="Whether an automated response was sent."
    )
    reply_log_id: Optional[str] = Field(
        None, description="ID of the reply_log row created."
    )
    error: Optional[str] = Field(
        None, description="Error message if processing failed."
    )


# LEAD MATCHING

def _match_lead_by_resend_id(resend_message_id: str) -> Optional[dict]:
    """Match a reply to a lead via the Resend message ID stored in outreach_log."""
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT l.*, ol.email_number as last_email_sent
           FROM outreach_log ol
           JOIN leads l ON ol.lead_id = l.id
           WHERE ol.resend_message_id = ?
           ORDER BY ol.sent_at DESC LIMIT 1""",
        (resend_message_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _match_lead_by_email(from_email: str) -> Optional[dict]:
    """Fallback: match by sender email address."""
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT l.*, ol.email_number as last_email_sent
           FROM leads l
           JOIN outreach_log ol ON ol.lead_id = l.id
           WHERE l.email = ? AND l.status = ?
           ORDER BY ol.sent_at DESC LIMIT 1""",
        (from_email, LeadStatus.ACTIVE)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _get_campaign_context(campaign_id: str) -> Optional[dict]:
    """Get ICP and product brief for a campaign."""
    db = get_db()
    icp = db.get_icp(campaign_id)
    brief = db.get_product_brief(campaign_id)
    return {"icp": icp, "brief": brief}


# REPLY LOG

def _save_reply_log(
    lead_id: str,
    campaign_id: str,
    user_id: str,
    event: InboundReplyEvent,
    agent_output: ReplyAgentOutput,
    response_sent: bool,
    response_body: Optional[str],
    referral_email: Optional[str],
    referral_name: Optional[str],
) -> str:
    """Write to reply_log. Returns log ID."""
    db = get_db()
    log_id = str(uuid.uuid4())
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        """INSERT INTO reply_log
           (id, lead_id, campaign_id, user_id, resend_inbound_id,
            from_email, subject, body_text, body_html,
            classification, confidence_score, agent_decision,
            referral_email, referral_name,
            response_sent, response_body, responded_at,
            received_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            log_id, lead_id, campaign_id, user_id, event.resend_inbound_id,
            event.from_email, event.subject, event.body_text, event.body_html,
            agent_output.classification, agent_output.confidence_score,
            agent_output.recommended_action,
            referral_email, referral_name,
            1 if response_sent else 0, response_body,
            now if response_sent else None,
            now, now, now,
        )
    )
    conn.commit()
    conn.close()
    return log_id


def _create_referral_lead(
    original_lead: dict,
    referral_name: Optional[str],
    referral_email: str,
) -> str:
    """Create a new lead from a referral. Returns new lead ID."""
    db = get_db()
    new_lead = db.save_lead(
        campaign_id=original_lead["campaign_id"],
        user_id=original_lead["user_id"],
        lead_data={
            "name": referral_name,
            "first_name": referral_name.split()[0] if referral_name else None,
            "last_name": " ".join(referral_name.split()[1:]) if referral_name and len(referral_name.split()) > 1 else None,
            "email": referral_email,
            "email_status": "UNVERIFIED",
            "company": original_lead.get("company"),
            "industry": original_lead.get("industry"),
            "location": original_lead.get("location"),
            "country": original_lead.get("country"),
            "provider": "referral",
            "type": original_lead.get("lead_type", "business"),
        }
    )
    logger.info(
        f"[ReplyHandler] Created referral lead {new_lead['id'][:8]} "
        f"<{referral_email}> from lead {original_lead['id'][:8]}"
    )
    return new_lead["id"]


async def _send_response(
    lead: dict,
    agent_output: ReplyAgentOutput,
    event: InboundReplyEvent,
    outreach_settings,
) -> bool:
    """Send the drafted response via Resend. Returns True if successful."""
    if not agent_output.drafted_response_body:
        return False

    try:
        resend_sdk.api_key = outreach_settings.resend_api_key

        # Replace sender name placeholder
        body = agent_output.drafted_response_body.replace(
            "{{sender_name}}", outreach_settings.sending_name
        )

        params = {
            "from": f"{outreach_settings.sending_name} <{outreach_settings.sending_email}>",
            "to": [event.from_email],
            "subject": agent_output.drafted_response_subject or f"Re: {event.subject or 'Your inquiry'}",
            "html": body.replace("\n", "<br>"),
            "text": body,
            "reply_to": outreach_settings.sending_email,
            "tags": [
                {"name": "lead_id", "value": lead["id"][:50]},
                {"name": "email_type", "value": "reply"},
            ],
        }

        result = await resend_sdk.Emails.send_async(params)
        logger.info(
            f"[ReplyHandler] Response sent to {event.from_email} "
            f"— Resend ID: {getattr(result, 'id', 'unknown')}"
        )
        return True

    except Exception as e:
        logger.error(f"[ReplyHandler] Failed to send response: {e}")
        return False


# MAIN HANDLER

async def handle_inbound_reply(event: InboundReplyEvent) -> ReplyHandlerOutput:
    """
    Full reply processing pipeline.
    Called by the Resend inbound webhook handler.
    """
    db = get_db()

    # ── 1. Match lead 
    lead = None
    if event.in_reply_to:
        lead = _match_lead_by_resend_id(event.in_reply_to)
    if not lead:
        lead = _match_lead_by_email(event.from_email)
    if not lead:
        logger.warning(
            f"[ReplyHandler] Could not match reply from {event.from_email} to any lead"
        )
        return ReplyHandlerOutput(
            lead_matched=False,
            error=f"No lead found for email {event.from_email}"
        )

    lead_id = lead["id"]
    campaign_id = lead["campaign_id"]
    user_id = lead["user_id"]
    last_email_sent = lead.get("last_email_sent", 1)

    logger.info(
        f"[ReplyHandler] Reply matched to lead {lead_id[:8]} "
        f"({lead.get('name')}) — campaign {campaign_id[:8]}"
    )

    # ── 2. Get context 
    ctx = _get_campaign_context(campaign_id)
    brief = ctx.get("brief") or {}
    icp_raw = ctx.get("icp")
    icp_md = _format_icp_markdown(icp_raw)
    brief_ext = _format_product_brief_extended(brief)
    lead_details_md = _format_lead_details_markdown(lead)

    db_path = getattr(db, "db_path", None)
    if db_path:
        conversation_history = _build_conversation_history(
            db_path, lead_id, event.resend_inbound_id
        )
        original_subject = _lookup_original_subject(
            db_path, lead_id, int(last_email_sent or 1)
        )
    else:
        conversation_history = (
            "(Email thread history is unavailable: database path not exposed in this environment.)"
        )
        original_subject = None

    outreach_settings = get_outreach_settings(user_id)

    # ── 3. Pre-fetch RAG context (targeted retrieval — policies, templates, FAQs)
    rag_context = None
    try:
        rag_context = retrieve_reply_rag_context(
            user_id,
            event.body_text,
            product_name=brief.get("product_name", "our product"),
            product_pain=brief.get("pain_it_solves", "") or "",
        )
    except Exception as e:
        logger.warning(f"[ReplyHandler] RAG retrieval failed: {e}")

    # ── 4. Run reply agent 
    agent_input = ReplyAgentInput(
        lead_id=lead_id,
        lead_name=lead.get("name"),
        lead_email=event.from_email,
        lead_company=lead.get("company"),
        lead_title=lead.get("title"),
        reply_subject=event.subject,
        reply_body_text=event.body_text,
        reply_body_html=event.body_html,
        original_email_number=int(last_email_sent or 1),
        original_subject=original_subject,
        product_name=brief.get("product_name", "our product"),
        product_pain=brief.get("pain_it_solves", ""),
        product_differentiators=brief.get("key_differentiators") or [],
        icp_context=icp_md,
        lead_details_text=lead_details_md,
        product_brief_extended=brief_ext,
        conversation_history=conversation_history,
        rag_context=rag_context,
        sender_name=outreach_settings.sending_name if outreach_settings else "the team",
        cal_link=outreach_settings.cal_link if outreach_settings else None,
    )

    try:
        agent_output = await run_reply_agent(agent_input)
    except Exception as e:
        logger.error(f"[ReplyHandler] Reply agent failed: {e}")
        return ReplyHandlerOutput(
            lead_id=lead_id,
            lead_matched=True,
            error=str(e),
        )

    # ── 5. Execute action 
    action = agent_output.recommended_action
    response_sent = False
    response_body = agent_output.drafted_response_body
    referral_email = None
    referral_name = None

    if action == "reply_with_rag":
        # Send drafted response, mark lead Replied
        if outreach_settings:
            response_sent = await _send_response(
                lead, agent_output, event, outreach_settings
            )
        db.update_lead_status(lead_id, LeadStatus.REPLIED)
        _cancel_followups(lead_id, reason="replied")

    elif action == "close_thread":
        # Send polite close, mark Inactive
        if outreach_settings:
            response_sent = await _send_response(
                lead, agent_output, event, outreach_settings
            )
        db.update_lead_status(lead_id, LeadStatus.INACTIVE)
        _cancel_followups(lead_id, reason="not_interested")

    elif action == "pause_lead":
        # OOF — pause follow-ups, mark Paused, resume after N days
        days = agent_output.resume_after_days or OOF_PAUSE_DAYS
        from backend.core.outreach.sender import _pause_followups, _date_plus_days
        resume_date = _date_plus_days(days)
        _pause_followups(lead_id, resume_date)
        db.update_lead_status(lead_id, LeadStatus.PAUSED)
        logger.info(
            f"[ReplyHandler] Lead {lead_id[:8]} paused until {resume_date} (OOF)"
        )

    elif action == "do_not_contact":
        # Opt-out — cancel everything, mark Do Not Contact
        _cancel_followups(lead_id, reason="opt_out")
        db.update_lead_status(lead_id, LeadStatus.DO_NOT_CONTACT)
        logger.info(f"[ReplyHandler] Lead {lead_id[:8]} marked Do Not Contact")

    elif action == "create_referral":
        # Wrong person — create new lead from referral
        if agent_output.referral and agent_output.referral.email:
            referral_email = agent_output.referral.email
            referral_name = agent_output.referral.name
            new_lead_id = _create_referral_lead(lead, referral_name, referral_email)
            # Note: referral lead goes straight to outreach
            # The API endpoint POST /outreach/{campaign_id}/leads/{lead_id}/send
            # should be called with the new lead ID
        db.update_lead_status(lead_id, LeadStatus.TRANSFERRED)
        _cancel_followups(lead_id, reason="transferred")

    elif action == "flag_review":
        # Ambiguous — flag for human review
        db.update_lead_status(lead_id, LeadStatus.OUTREACH_REVIEW)
        logger.info(
            f"[ReplyHandler] Lead {lead_id[:8]} flagged for review "
            f"(confidence={agent_output.confidence_score:.0%})"
        )

    # ── 6. Log to reply_log
    log_id = _save_reply_log(
        lead_id=lead_id,
        campaign_id=campaign_id,
        user_id=user_id,
        event=event,
        agent_output=agent_output,
        response_sent=response_sent,
        response_body=response_body,
        referral_email=referral_email,
        referral_name=referral_name,
    )

    logger.info(
        f"[ReplyHandler] Complete — lead={lead_id[:8]} "
        f"classification={agent_output.classification} "
        f"action={action} "
        f"response_sent={response_sent}"
    )

    return ReplyHandlerOutput(
        lead_id=lead_id,
        lead_matched=True,
        classification=agent_output.classification,
        action_taken=action,
        response_sent=response_sent,
        reply_log_id=log_id,
    )
