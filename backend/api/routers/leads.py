"""
leads.py
--------
Lead endpoints:
  GET /campaigns/{campaign_id}/leads              list all leads
  GET /campaigns/{campaign_id}/leads/{lead_id}    get single lead with full details
"""

import json
import logging
import sqlite3
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.dependencies.auth import get_current_user, verify_campaign_ownership
from backend.api.schemas.responses import (
    LeadListResponse, LeadResponse,
    EnrichmentSummary, QualificationSummary,
)
from backend.infrastructure.factory import get_db
from backend.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Leads"])


# ── Helpers

def _loads(val):
    if val and isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return val or []


def _get_enrichment_for_lead(db, lead_id: str) -> Optional[EnrichmentSummary]:
    """Fetch enrichment result for a lead from the DB."""
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT * FROM enrichment_results WHERE lead_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (lead_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    r = dict(row)
    return EnrichmentSummary(
        identity_status=r.get("identity_status"),
        confidence_score=r.get("confidence_score"),
        current_title=r.get("current_title"),
        company_signals=_loads(r.get("company_signals")),
        notable_achievements=_loads(r.get("notable_achievements")),
        discrepancies=_loads(r.get("discrepancies")),
        enrichment_summary=r.get("enrichment_summary"),
    )


def _get_qualification_for_lead(db, lead_id: str) -> Optional[QualificationSummary]:
    """Fetch qualification result for a lead from the DB."""
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT * FROM qualification_results WHERE lead_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (lead_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    r = dict(row)
    return QualificationSummary(
        decision=r.get("decision"),
        icp_match_score=r.get("icp_match_score"),
        decision_reason=r.get("decision_reason"),
        blocking_issues=_loads(r.get("blocking_issues")),
        review_flags=_loads(r.get("review_flags")),
        recommended_angle=r.get("recommended_angle"),
    )


def _build_lead_response(lead: Dict, db, include_details: bool = False) -> LeadResponse:
    enrichment = _get_enrichment_for_lead(db, lead["id"]) if include_details else None
    qualification = _get_qualification_for_lead(db, lead["id"]) if include_details else None

    return LeadResponse(
        id=lead["id"],
        campaign_id=lead["campaign_id"],
        status=lead["status"],
        name=lead.get("name"),
        first_name=lead.get("first_name"),
        last_name=lead.get("last_name"),
        title=lead.get("title"),
        seniority=lead.get("seniority"),
        email=lead.get("email"),
        email_status=lead.get("email_status"),
        phone=lead.get("phone"),
        company=lead.get("company"),
        company_size=lead.get("company_size"),
        industry=lead.get("industry"),
        location=lead.get("location"),
        country=lead.get("country"),
        linkedin=lead.get("linkedin"),
        provider=lead.get("provider"),
        lead_type=lead.get("lead_type"),
        enrichment=enrichment,
        qualification=qualification,
        created_at=lead.get("created_at", ""),
        updated_at=lead.get("updated_at", ""),
    )


# ── Endpoints

@router.get(
    "/campaigns/{campaign_id}/leads",
    response_model=LeadListResponse,
)
async def list_leads(
    campaign_id: str,
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by lead status: ingested, queried, enriched, qualified, review, disqualified, email_written"
    ),
    user: Dict = Depends(get_current_user),
):
    """
    List all leads for a campaign.
    Optionally filter by status.
    Enrichment and qualification details are NOT included in list view — use the single lead endpoint.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    leads = db.get_leads_for_campaign(campaign_id, status=status_filter)

    return LeadListResponse(
        leads=[_build_lead_response(l, db, include_details=False) for l in leads],
        total=len(leads),
        campaign_id=campaign_id,
    )


@router.get(
    "/campaigns/{campaign_id}/leads/{lead_id}",
    response_model=LeadResponse,
)
async def get_lead(
    campaign_id: str,
    lead_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Get a single lead with full enrichment and qualification details.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    # Fetch lead and verify it belongs to this campaign
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND campaign_id = ?",
        (lead_id, campaign_id)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found in campaign {campaign_id}.",
        )

    lead = dict(row)
    return _build_lead_response(lead, db, include_details=True)
