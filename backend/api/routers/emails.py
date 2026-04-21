"""
emails.py
---------
Email sequence endpoints:
  GET /campaigns/{campaign_id}/emails                 list all sequences
  GET /campaigns/{campaign_id}/emails/{lead_id}       get sequence for a lead
  PUT /campaigns/{campaign_id}/emails/{lead_id}       update/edit a sequence manually
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies.auth import get_current_user, verify_campaign_ownership
from backend.api.schemas.requests import UpdateEmailRequest
from backend.api.schemas.responses import (
    EmailListResponse, EmailSequenceResponse, EmailDetail, MessageResponse
)
from backend.infrastructure.factory import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Emails"])


# ── Helpers

def _get_lead_name(db, lead_id: str) -> Optional[str]:
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT name FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return dict(row).get("name") if row else None


def _build_email_response(seq: Dict, db) -> EmailSequenceResponse:
    lead_name = _get_lead_name(db, seq["lead_id"])
    return EmailSequenceResponse(
        id=seq["id"],
        lead_id=seq["lead_id"],
        campaign_id=seq["campaign_id"],
        lead_name=lead_name,
        lead_email=seq["lead_email"],
        email_1=EmailDetail(
            subject=seq.get("email_1_subject"),
            body=seq.get("email_1_body"),
        ),
        email_2=EmailDetail(
            subject=seq.get("email_2_subject"),
            body=seq.get("email_2_body"),
        ),
        email_3=EmailDetail(
            subject=seq.get("email_3_subject"),
            body=seq.get("email_3_body"),
        ),
        sequence_notes=seq.get("sequence_notes"),
        email_1_sent_at=seq.get("email_1_sent_at"),
        email_2_sent_at=seq.get("email_2_sent_at"),
        email_3_sent_at=seq.get("email_3_sent_at"),
        created_at=seq.get("created_at", ""),
        updated_at=seq.get("updated_at", ""),
    )


def _get_sequences_for_campaign(db, campaign_id: str) -> List[Dict]:
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM email_sequences WHERE campaign_id = ? ORDER BY created_at",
        (campaign_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_sequence_by_lead(db, campaign_id: str, lead_id: str) -> Optional[Dict]:
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


# ── Endpoints

@router.get(
    "/campaigns/{campaign_id}/emails",
    response_model=EmailListResponse,
)
async def list_emails(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    List all generated email sequences for a campaign.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    sequences = _get_sequences_for_campaign(db, campaign_id)

    return EmailListResponse(
        sequences=[_build_email_response(s, db) for s in sequences],
        total=len(sequences),
        campaign_id=campaign_id,
    )


@router.get(
    "/campaigns/{campaign_id}/emails/{lead_id}",
    response_model=EmailSequenceResponse,
)
async def get_email_sequence(
    campaign_id: str,
    lead_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Get the full 3-email sequence for a specific lead.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    seq = _get_sequence_by_lead(db, campaign_id, lead_id)
    if not seq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No email sequence found for lead {lead_id} in campaign {campaign_id}.",
        )

    return _build_email_response(seq, db)


@router.put(
    "/campaigns/{campaign_id}/emails/{lead_id}",
    response_model=EmailSequenceResponse,
)
async def update_email_sequence(
    campaign_id: str,
    lead_id: str,
    body: UpdateEmailRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Manually edit an email sequence before sending.
    Partial update — only provided fields are changed.
    Allows the user to personalise or correct AI-generated emails.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    seq = _get_sequence_by_lead(db, campaign_id, lead_id)
    if not seq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No email sequence found for lead {lead_id} in campaign {campaign_id}.",
        )

    # Build updates dict — only fields that were provided
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return _build_email_response(seq, db)

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [seq["id"]]

    conn = sqlite3.connect(db.db_path)
    conn.execute(f"UPDATE email_sequences SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()

    # Re-fetch and return
    updated_seq = _get_sequence_by_lead(db, campaign_id, lead_id)
    return _build_email_response(updated_seq, db)
