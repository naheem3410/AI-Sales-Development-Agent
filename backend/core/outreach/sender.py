"""
sender.py
---------
Resend email sender for the outreach layer.

Responsibilities:
  - Send Email 1, 2, or 3 for a lead using the user's own Resend API key
  - Store every send in outreach_log
  - Schedule follow-ups in followup_schedule after each send
  - Mark lead status as Active after Email 1

Timing (industry best practice):
  Email 1 → day 0  (send immediately on trigger)
  Email 2 → day 3
  Email 3 → day 7
  Mark Inactive → day 14 if no reply

Per-user isolation:
  Every user has their own Resend account and API key.
  We never use a shared platform key for outbound sends.

Local dev / testing:
  Set OUTREACH_DRY_RUN=true to skip actual Resend API calls.
  All DB writes and scheduling still happen — only the API call is skipped.

  Set OUTREACH_TEST_RECIPIENT_EMAIL=you@example.com to deliver every outreach send
  to your inbox instead of the lead's address (manual sends + scheduler). Remove in production.
"""

import os
import uuid
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from backend.infrastructure.factory import get_db
from backend.core.enums import LeadStatus

logger = logging.getLogger(__name__)

OUTREACH_DRY_RUN = os.getenv("OUTREACH_DRY_RUN", "false").lower() == "true"

# When set, Resend "to" uses this address (lead email is ignored for delivery).
OUTREACH_TEST_RECIPIENT_EMAIL = (os.getenv("OUTREACH_TEST_RECIPIENT_EMAIL") or "").strip()

# Follow-up schedule in days from Email 1 send date
FOLLOWUP_SCHEDULE_DAYS = {
    2: 3,   # Email 2 → day 3
    3: 7,   # Email 3 → day 7
}
INACTIVE_AFTER_DAYS = 14


# ── Input / Output Models

class SendEmailInput(BaseModel):
    """Input for sending a single outreach email to a lead."""

    lead_id: str = Field(..., description="Database ID of the lead to send to.")
    campaign_id: str = Field(..., description="Campaign this lead belongs to.")
    user_id: str = Field(..., description="User triggering the send — determines which Resend key to use.")
    email_number: int = Field(..., ge=1, le=3, description="Which email in the sequence: 1, 2, or 3.")
    to_email: str = Field(..., description="Recipient email address.")
    from_email: str = Field(..., description="Verified sender email address from user's Resend account.")
    from_name: str = Field(..., description="Sender display name e.g. 'John from Acme'.")
    subject: str = Field(..., description="Email subject line.")
    body_html: str = Field(..., description="Email body as HTML.")
    body_text: Optional[str] = Field(None, description="Plain text fallback body.")
    reply_to: Optional[str] = Field(None, description="Reply-to address — used to capture replies in Resend inbound.")
    resend_api_key: str = Field(..., description="User's own Resend API key.")


class SendEmailOutput(BaseModel):
    """Result of an outreach email send attempt."""

    success: bool = Field(..., description="Whether the send was successful.")
    outreach_log_id: str = Field(..., description="ID of the outreach_log row created.")
    resend_message_id: Optional[str] = Field(None, description="Resend's message ID returned on success.")
    error: Optional[str] = Field(None, description="Error message if send failed.")
    followups_scheduled: int = Field(0, description="Number of follow-up rows created in followup_schedule.")


class OutreachSettings(BaseModel):
    """User's outreach configuration loaded from user_outreach_settings."""

    user_id: str = Field(..., description="User ID.")
    resend_api_key: str = Field(..., description="User's Resend API key.")
    sending_domain: str = Field(..., description="Verified sending domain.")
    sending_email: str = Field(..., description="From email address.")
    sending_name: str = Field(..., description="From display name.")
    cal_link: Optional[str] = Field(None, description="Cal.com booking link to embed in replies.")


# ── DB Helpers

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _date_plus_days(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def get_outreach_settings(user_id: str) -> Optional[OutreachSettings]:
    """Load and validate outreach settings for a user from the DB."""
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM user_outreach_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    r = dict(row)
    if not r.get("is_configured"):
        return None

    return OutreachSettings(
        user_id=user_id,
        resend_api_key=r["resend_api_key"],
        sending_domain=r["sending_domain"],
        sending_email=r["sending_email"],
        sending_name=r["sending_name"],
        cal_link=r.get("cal_link"),
    )


def _save_outreach_log(
    lead_id: str,
    campaign_id: str,
    user_id: str,
    email_number: int,
    from_email: str,
    to_email: str,
    subject: str,
    body_snapshot: str,
    resend_message_id: Optional[str],
    status: str,
) -> str:
    """Write a row to outreach_log. Returns the new log ID."""
    db = get_db()
    log_id = str(uuid.uuid4())
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        """INSERT INTO outreach_log
           (id, lead_id, campaign_id, user_id, email_number, resend_message_id,
            from_email, to_email, subject, body_snapshot, status, sent_at,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (log_id, lead_id, campaign_id, user_id, email_number, resend_message_id,
         from_email, to_email, subject, body_snapshot[:2000], status, now, now, now)
    )
    conn.commit()
    conn.close()
    return log_id


def _schedule_followups(
    lead_id: str,
    campaign_id: str,
    user_id: str,
    from_email_number: int,
) -> int:
    """
    Schedule follow-up emails after a successful send.
    from_email_number=1 → schedules Email 2 (day 3) and Email 3 (day 7)
    from_email_number=2 → schedules Email 3 (day 7)
    from_email_number=3 → nothing to schedule
    Returns count of rows created.
    """
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    now = _now_iso()
    count = 0

    for email_num, days_from_now in FOLLOWUP_SCHEDULE_DAYS.items():
        if email_num <= from_email_number:
            continue

        scheduled_date = _date_plus_days(days_from_now)
        schedule_id = str(uuid.uuid4())
        conn.execute(
            """INSERT OR IGNORE INTO followup_schedule
               (id, lead_id, campaign_id, user_id, email_number, scheduled_date,
                status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (schedule_id, lead_id, campaign_id, user_id, email_num,
             scheduled_date, "pending", now, now)
        )
        count += 1
        logger.info(
            f"[Sender] Scheduled Email {email_num} for lead {lead_id[:8]} "
            f"on {scheduled_date}"
        )

    conn.commit()
    conn.close()
    return count


def _cancel_followups(lead_id: str, reason: str):
    """Cancel all pending follow-ups for a lead. Called when reply received."""
    db = get_db()
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        """UPDATE followup_schedule
           SET status = 'cancelled', cancelled_at = ?, cancel_reason = ?, updated_at = ?
           WHERE lead_id = ? AND status = 'pending'""",
        (now, reason, now, lead_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"[Sender] Cancelled pending follow-ups for lead {lead_id[:8]} — {reason}")


def _pause_followups(lead_id: str, resume_date: str):
    """Pause all pending follow-ups for a lead. Used for OOO."""
    db = get_db()
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        """UPDATE followup_schedule
           SET status = 'paused', paused_until = ?, updated_at = ?
           WHERE lead_id = ? AND status = 'pending'""",
        (resume_date, now, lead_id)
    )
    conn.commit()
    conn.close()
    logger.info(
        f"[Sender] Paused follow-ups for lead {lead_id[:8]} until {resume_date}"
    )


def _resume_followups(lead_id: str):
    """
    Resume paused follow-ups after OOO period ends.
    Continues from where the sequence left off — does not restart.
    Adjusts scheduled_date to today + original remaining gap.
    """
    db = get_db()
    now = _now_iso()
    today = _today()
    conn = sqlite3.connect(db.db_path)

    paused = conn.execute(
        """SELECT * FROM followup_schedule
           WHERE lead_id = ? AND status = 'paused'
           ORDER BY email_number""",
        (lead_id,)
    ).fetchall()

    for i, row in enumerate(paused):
        r = dict(row)
        # Space them out from today: first pending → today+1, second → today+4 etc.
        new_date = _date_plus_days(1 + i * 4)
        conn.execute(
            """UPDATE followup_schedule
               SET status = 'pending', scheduled_date = ?, paused_until = NULL, updated_at = ?
               WHERE id = ?""",
            (new_date, now, r["id"])
        )
        logger.info(
            f"[Sender] Resumed Email {r['email_number']} for lead {lead_id[:8]} "
            f"→ rescheduled to {new_date}"
        )

    conn.commit()
    conn.close()


# ── Main Send Function

async def send_outreach_email(inp: SendEmailInput) -> SendEmailOutput:
    """
    Send an outreach email via Resend SDK using the user's own API key.
    Writes to outreach_log, schedules follow-ups, updates lead status.
    """
    db = get_db()
    resend_message_id = None
    status = "sent"
    error = None

    intended_recipient = (inp.to_email or "").strip()
    effective_to = OUTREACH_TEST_RECIPIENT_EMAIL or intended_recipient
    if OUTREACH_TEST_RECIPIENT_EMAIL and OUTREACH_TEST_RECIPIENT_EMAIL != intended_recipient:
        logger.warning(
            f"[Sender] OUTREACH_TEST_RECIPIENT_EMAIL active — delivering to {effective_to} "
            f"(lead would have been {intended_recipient})"
        )

    if OUTREACH_DRY_RUN:
        logger.info(
            f"[Sender] DRY RUN — would send Email {inp.email_number} "
            f"to {effective_to} via {inp.from_email}"
            + (
                f" [lead recipient: {intended_recipient}]"
                if effective_to != intended_recipient
                else ""
            )
        )
        resend_message_id = f"dry_run_{uuid.uuid4().hex[:12]}"
    else:
        try:
            import resend as resend_sdk
            resend_sdk.api_key = inp.resend_api_key

            params = {
                "from": f"{inp.from_name} <{inp.from_email}>",
                "to": [effective_to],
                "subject": inp.subject,
                "html": inp.body_html,
                "tags": [
                    {"name": "lead_id", "value": inp.lead_id[:50]},
                    {"name": "campaign_id", "value": inp.campaign_id[:50]},
                    {"name": "email_number", "value": str(inp.email_number)},
                ],
            }

            if inp.body_text:
                params["text"] = inp.body_text
            if inp.reply_to:
                params["reply_to"] = inp.reply_to

            result = await resend_sdk.Emails.send_async(params)
            resend_message_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            logger.info(
                f"[Sender] Sent Email {inp.email_number} to {effective_to} "
                f"— Resend ID: {resend_message_id}"
                + (
                    f" (lead: {intended_recipient})"
                    if effective_to != intended_recipient
                    else ""
                )
            )

        except Exception as e:
            logger.error(f"[Sender] Resend send failed: {e}")
            error = str(e)
            status = "failed"

    # Always write to outreach_log regardless of success/failure
    log_id = _save_outreach_log(
        lead_id=inp.lead_id,
        campaign_id=inp.campaign_id,
        user_id=inp.user_id,
        email_number=inp.email_number,
        from_email=inp.from_email,
        to_email=effective_to,
        subject=inp.subject,
        body_snapshot=inp.body_html,
        resend_message_id=resend_message_id,
        status=status,
    )

    followups_scheduled = 0

    if status == "sent":
        # Update lead status to Active after Email 1
        if inp.email_number == 1:
            db.update_lead_status(inp.lead_id, LeadStatus.ACTIVE)

        # Schedule follow-ups
        followups_scheduled = _schedule_followups(
            lead_id=inp.lead_id,
            campaign_id=inp.campaign_id,
            user_id=inp.user_id,
            from_email_number=inp.email_number,
        )

    return SendEmailOutput(
        success=(status == "sent"),
        outreach_log_id=log_id,
        resend_message_id=resend_message_id,
        error=error,
        followups_scheduled=followups_scheduled,
    )
