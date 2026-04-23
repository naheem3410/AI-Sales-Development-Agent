"""
scheduler.py
------------
Daily follow-up scheduler.

What it does:
  1. Queries followup_schedule for all 'pending' rows where scheduled_date <= today
  2. For each overdue follow-up:
     - Verifies the lead is still Active (not replied, opted out, etc.)
     - Fetches the email sequence from email_sequences
     - Sends the next email via Resend using the user's outreach settings
     - Updates the followup_schedule row to 'sent'
  3. Marks leads as Inactive if:
     - All follow-ups are sent
     - No reply has been logged
     - 14+ days have passed since Email 1

Local: Run manually or via cron: python -m outreach.scheduler.scheduler
Production: Triggered daily by AWS EventBridge → Lambda

Input / Output:
  SchedulerRunInput  — parameters for the run (dry_run, campaign filter)
  SchedulerRunOutput — summary of what was processed
"""

import os
import sqlite3
import logging
import asyncio
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List

from pydantic import BaseModel, Field

from backend.infrastructure.factory import get_db
from backend.core.enums import LeadStatus
from backend.core.outreach.sender import (
    SendEmailInput, send_outreach_email,
    get_outreach_settings, _cancel_followups, _now_iso, _date_plus_days
)

logger = logging.getLogger(__name__)

INACTIVE_AFTER_DAYS = 14



# INPUT / OUTPUT MODELS

class SchedulerRunInput(BaseModel):
    """Parameters for a scheduler run."""

    dry_run: bool = Field(
        False,
        description=(
            "If True, log what would be sent but do not actually send or update DB. "
            "Use for testing the scheduler logic."
        )
    )
    campaign_id_filter: Optional[str] = Field(
        None,
        description="If set, only process follow-ups for this campaign. Otherwise process all."
    )
    user_id_filter: Optional[str] = Field(
        None,
        description="If set, only process follow-ups for this user. Otherwise process all."
    )


class FollowUpProcessed(BaseModel):
    """Record of a single follow-up that was processed."""

    lead_id: str = Field(..., description="Lead that received the follow-up.")
    lead_name: Optional[str] = Field(None, description="Lead's name.")
    lead_email: str = Field(..., description="Lead's email address.")
    campaign_id: str = Field(..., description="Campaign the lead belongs to.")
    email_number: int = Field(..., description="Which email was sent (2 or 3).")
    success: bool = Field(..., description="Whether the send was successful.")
    error: Optional[str] = Field(None, description="Error message if send failed.")


class LeadMarkedInactive(BaseModel):
    """Record of a lead marked Inactive after sequence exhaustion."""

    lead_id: str = Field(..., description="Lead that was marked Inactive.")
    lead_name: Optional[str] = Field(None, description="Lead's name.")
    campaign_id: str = Field(..., description="Campaign the lead belongs to.")
    days_since_email1: int = Field(..., description="Days since Email 1 was sent.")


class SchedulerRunOutput(BaseModel):
    """Summary of a scheduler run."""

    run_date: str = Field(..., description="Date this run processed (YYYY-MM-DD).")
    dry_run: bool = Field(..., description="Whether this was a dry run.")
    followups_processed: List[FollowUpProcessed] = Field(
        default_factory=list,
        description="All follow-ups that were attempted."
    )
    leads_marked_inactive: List[LeadMarkedInactive] = Field(
        default_factory=list,
        description="Leads marked Inactive after sequence exhaustion."
    )
    total_sent: int = Field(0, description="Number of emails successfully sent.")
    total_failed: int = Field(0, description="Number of send failures.")
    total_inactive: int = Field(0, description="Number of leads marked Inactive.")
    errors: List[str] = Field(default_factory=list, description="Any scheduler-level errors.")



# DB HELPERS

def _get_overdue_followups(
    campaign_id_filter: Optional[str],
    user_id_filter: Optional[str],
) -> List[dict]:
    """
    Fetch all pending follow-ups where scheduled_date <= today.
    Excludes paused follow-ups.
    """
    db = get_db()
    today = date.today().isoformat()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT fs.*, l.name as lead_name, l.email as lead_email,
               l.status as lead_status, l.campaign_id as lead_campaign_id
        FROM followup_schedule fs
        JOIN leads l ON fs.lead_id = l.id
        WHERE fs.status = 'pending'
          AND fs.scheduled_date <= ?
    """
    params = [today]

    if campaign_id_filter:
        query += " AND fs.campaign_id = ?"
        params.append(campaign_id_filter)

    if user_id_filter:
        query += " AND fs.user_id = ?"
        params.append(user_id_filter)

    query += " ORDER BY fs.scheduled_date ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_active_leads_past_inactive_date(
    campaign_id_filter: Optional[str],
    user_id_filter: Optional[str],
) -> List[dict]:
    """
    Find Active leads where:
    - All follow-ups are sent or cancelled
    - Email 1 was sent >= INACTIVE_AFTER_DAYS days ago
    - No reply has been logged
    These should be marked Inactive.
    """
    db = get_db()
    cutoff_date = (date.today() - timedelta(days=INACTIVE_AFTER_DAYS)).isoformat()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT l.id, l.name, l.campaign_id, l.user_id, ol.sent_at
        FROM leads l
        JOIN outreach_log ol ON ol.lead_id = l.id AND ol.email_number = 1
        WHERE l.status = ?
          AND ol.sent_at <= ?
          AND NOT EXISTS (
              SELECT 1 FROM reply_log rl WHERE rl.lead_id = l.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM followup_schedule fs
              WHERE fs.lead_id = l.id AND fs.status = 'pending'
          )
    """
    params = [LeadStatus.ACTIVE, cutoff_date + "T00:00:00+00:00"]

    if campaign_id_filter:
        query += " AND l.campaign_id = ?"
        params.append(campaign_id_filter)

    if user_id_filter:
        query += " AND l.user_id = ?"
        params.append(user_id_filter)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_email_sequence(campaign_id: str, lead_id: str) -> Optional[dict]:
    """Fetch the email sequence for a lead."""
    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT * FROM email_sequences
           WHERE campaign_id = ? AND lead_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (campaign_id, lead_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _mark_followup_sent(followup_id: str):
    db = get_db()
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        "UPDATE followup_schedule SET status='sent', sent_at=?, updated_at=? WHERE id=?",
        (now, now, followup_id)
    )
    conn.commit()
    conn.close()


def _mark_followup_failed(followup_id: str):
    db = get_db()
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.execute(
        "UPDATE followup_schedule SET status='failed', updated_at=? WHERE id=?",
        (now, followup_id)
    )
    conn.commit()
    conn.close()


def _mark_lead_inactive(lead_id: str):
    db = get_db()
    db.update_lead_status(lead_id, LeadStatus.INACTIVE)
    logger.info(f"[Scheduler] Lead {lead_id[:8]} marked Inactive.")


# MAIN SCHEDULER


async def run_scheduler(inp: SchedulerRunInput) -> SchedulerRunOutput:
    """
    Run the daily follow-up scheduler.

    Steps:
    1. Find all overdue pending follow-ups
    2. For each: verify lead is still Active, fetch email sequence, send
    3. Find leads that should be marked Inactive
    4. Return summary
    """
    run_date = date.today().isoformat()
    output = SchedulerRunOutput(run_date=run_date, dry_run=inp.dry_run)

    logger.info(
        f"[Scheduler] Starting run for {run_date} "
        f"(dry_run={inp.dry_run})"
    )

    # ── Step 1: Process overdue follow-ups 
    overdue = _get_overdue_followups(
        inp.campaign_id_filter,
        inp.user_id_filter,
    )
    logger.info(f"[Scheduler] Found {len(overdue)} overdue follow-up(s)")

    for followup in overdue:
        lead_id = followup["lead_id"]
        campaign_id = followup["campaign_id"]
        user_id = followup["user_id"]
        email_number = followup["email_number"]
        followup_id = followup["id"]

        lead_name = followup.get("lead_name")
        lead_email = followup.get("lead_email")
        lead_status = followup.get("lead_status")

        # Skip if lead is no longer Active
        if lead_status != LeadStatus.ACTIVE:
            logger.info(
                f"[Scheduler] Skipping lead {lead_id[:8]} — "
                f"status is '{lead_status}', not active"
            )
            if not inp.dry_run:
                _mark_followup_sent(followup_id)  # mark as handled
            continue

        if inp.dry_run:
            logger.info(
                f"[Scheduler] DRY RUN — would send Email {email_number} "
                f"to {lead_email}"
            )
            output.followups_processed.append(FollowUpProcessed(
                lead_id=lead_id,
                lead_name=lead_name,
                lead_email=lead_email,
                campaign_id=campaign_id,
                email_number=email_number,
                success=True,
            ))
            output.total_sent += 1
            continue

        # Get user's outreach settings
        settings_obj = get_outreach_settings(user_id)
        if not settings_obj:
            error = f"User {user_id[:8]} has no outreach settings configured"
            logger.warning(f"[Scheduler] {error}")
            output.followups_processed.append(FollowUpProcessed(
                lead_id=lead_id,
                lead_name=lead_name,
                lead_email=lead_email or "",
                campaign_id=campaign_id,
                email_number=email_number,
                success=False,
                error=error,
            ))
            output.total_failed += 1
            continue

        # Get email sequence
        sequence = _get_email_sequence(campaign_id, lead_id)
        if not sequence:
            error = f"No email sequence found for lead {lead_id[:8]}"
            logger.warning(f"[Scheduler] {error}")
            output.followups_processed.append(FollowUpProcessed(
                lead_id=lead_id,
                lead_name=lead_name,
                lead_email=lead_email or "",
                campaign_id=campaign_id,
                email_number=email_number,
                success=False,
                error=error,
            ))
            output.total_failed += 1
            continue

        # Get the right email content
        subject_key = f"email_{email_number}_subject"
        body_key = f"email_{email_number}_body"
        subject = sequence.get(subject_key, f"Follow-up #{email_number - 1}")
        body = sequence.get(body_key, "")

        if not body:
            error = f"Email {email_number} body is empty for lead {lead_id[:8]}"
            logger.warning(f"[Scheduler] {error}")
            output.total_failed += 1
            continue

        # Send the email
        try:
            send_result = await send_outreach_email(SendEmailInput(
                lead_id=lead_id,
                campaign_id=campaign_id,
                user_id=user_id,
                email_number=email_number,
                to_email=lead_email or sequence["lead_email"],
                from_email=settings_obj.sending_email,
                from_name=settings_obj.sending_name,
                subject=subject,
                body_html=body,
                reply_to=settings_obj.sending_email,
                resend_api_key=settings_obj.resend_api_key,
            ))

            if send_result.success:
                _mark_followup_sent(followup_id)
                output.total_sent += 1
                logger.info(
                    f"[Scheduler] ✅ Sent Email {email_number} to {lead_email}"
                )
            else:
                _mark_followup_failed(followup_id)
                output.total_failed += 1
                logger.error(
                    f"[Scheduler] ❌ Failed to send Email {email_number} "
                    f"to {lead_email}: {send_result.error}"
                )

            output.followups_processed.append(FollowUpProcessed(
                lead_id=lead_id,
                lead_name=lead_name,
                lead_email=lead_email or "",
                campaign_id=campaign_id,
                email_number=email_number,
                success=send_result.success,
                error=send_result.error,
            ))

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Scheduler] Unexpected error for lead {lead_id[:8]}: {e}")
            output.followups_processed.append(FollowUpProcessed(
                lead_id=lead_id,
                lead_name=lead_name,
                lead_email=lead_email or "",
                campaign_id=campaign_id,
                email_number=email_number,
                success=False,
                error=error_msg,
            ))
            output.total_failed += 1

    # ── Step 2: Mark inactive leads 
    inactive_candidates = _get_active_leads_past_inactive_date(
        inp.campaign_id_filter,
        inp.user_id_filter,
    )
    logger.info(
        f"[Scheduler] Found {len(inactive_candidates)} lead(s) to mark Inactive"
    )

    for lead in inactive_candidates:
        lead_id = lead["id"]
        days_since = (date.today() - date.fromisoformat(
            lead["sent_at"][:10]
        )).days

        if not inp.dry_run:
            _mark_lead_inactive(lead_id)

        output.leads_marked_inactive.append(LeadMarkedInactive(
            lead_id=lead_id,
            lead_name=lead.get("name"),
            campaign_id=lead["campaign_id"],
            days_since_email1=days_since,
        ))
        output.total_inactive += 1

    logger.info(
        f"[Scheduler] Run complete — "
        f"sent={output.total_sent}, "
        f"failed={output.total_failed}, "
        f"inactive={output.total_inactive}"
    )

    return output


# CLI ENTRY POINT

async def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="SDA Follow-up Scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without sending")
    parser.add_argument("--campaign", help="Filter by campaign ID")
    parser.add_argument("--user", help="Filter by user ID")
    args = parser.parse_args()

    result = await run_scheduler(SchedulerRunInput(
        dry_run=args.dry_run,
        campaign_id_filter=args.campaign,
        user_id_filter=args.user,
    ))

    print(f"\n{'='*60}")
    print(f"Scheduler Run — {result.run_date} {'(DRY RUN)' if result.dry_run else ''}")
    print(f"{'='*60}")
    print(f"  Follow-ups processed : {len(result.followups_processed)}")
    print(f"  Sent successfully    : {result.total_sent}")
    print(f"  Failed               : {result.total_failed}")
    print(f"  Marked Inactive      : {result.total_inactive}")

    if result.followups_processed:
        print(f"\n  Processed:")
        for f in result.followups_processed:
            icon = "✅" if f.success else "❌"
            print(f"  {icon} Email {f.email_number} → {f.lead_email} "
                  f"({f.lead_name or 'Unknown'})"
                  + (f" — {f.error}" if f.error else ""))

    if result.leads_marked_inactive:
        print(f"\n  Marked Inactive:")
        for l in result.leads_marked_inactive:
            print(f"  ⚪ {l.lead_name or l.lead_id[:8]} "
                  f"({l.days_since_email1} days since Email 1)")


if __name__ == "__main__":
    import os
    os.environ.setdefault("SDA_ENV", "local")
    asyncio.run(main())
