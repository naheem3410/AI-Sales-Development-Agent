"""
analytics.py
------------
Analytics endpoint:
  GET /campaigns/{campaign_id}/summary   dashboard summary counts
"""

import logging
from typing import Dict

from fastapi import APIRouter, Depends

from backend.api.dependencies.auth import get_current_user, verify_campaign_ownership
from backend.api.schemas.responses import AnalyticsSummaryResponse
from backend.infrastructure.factory import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Analytics"])


@router.get(
    "/campaigns/{campaign_id}/summary",
    response_model=AnalyticsSummaryResponse,
)
async def get_campaign_summary(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Returns dashboard summary counts for a campaign.
    Used to populate the frontend dashboard cards:
    total leads / enriched / approved / review / rejected / emails written.
    Also includes approval rate and enrichment rate.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    summary = db.get_campaign_summary(campaign_id)

    total = summary["total_leads"]
    enriched = summary["enriched"]
    approved = summary["approved"]

    approval_rate = round(approved / total, 4) if total > 0 else None
    enrichment_rate = round(enriched / total, 4) if total > 0 else None

    return AnalyticsSummaryResponse(
        campaign_id=campaign_id,
        campaign_name=campaign["name"],
        campaign_status=campaign["status"],
        total_leads=total,
        enriched=enriched,
        approved=approved,
        review=summary["review"],
        rejected=summary["rejected"],
        emails_written=summary["emails_written"],
        approval_rate=approval_rate,
        enrichment_rate=enrichment_rate,
    )
