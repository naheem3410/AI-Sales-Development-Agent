"""
campaigns.py
------------
Campaign endpoints:
  POST   /campaigns                           create campaign + trigger onboarding
  GET    /campaigns                           list all campaigns for user
  GET    /campaigns/{campaign_id}             get single campaign
  DELETE /campaigns/{campaign_id}             cancel/delete campaign
  GET    /campaigns/{campaign_id}/icp         get ICP
  PUT    /campaigns/{campaign_id}/icp         update ICP
  GET    /campaigns/{campaign_id}/brief       get product brief
  PUT    /campaigns/{campaign_id}/brief       update product brief
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from backend.api.dependencies.auth import (
    get_current_user,
    require_active_subscription,
    verify_campaign_ownership,
)
from backend.api.schemas.requests import CreateCampaignRequest, UpdateICPRequest, UpdateBriefRequest
from backend.api.schemas.responses import (
    CampaignResponse, CampaignListResponse, CampaignSummary,
    ICPResponse, BriefResponse, MessageResponse,
)
from backend.infrastructure.factory import get_db
from backend.core.enums import CampaignStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


# ── Helpers

def _build_campaign_response(campaign: Dict, db) -> CampaignResponse:
    summary_raw = db.get_campaign_summary(campaign["id"])
    summary = CampaignSummary(**summary_raw) if summary_raw else None
    return CampaignResponse(
        id=campaign["id"],
        user_id=campaign["user_id"],
        name=campaign["name"],
        status=campaign["status"],
        website_url=campaign.get("website_url"),
        company_name=campaign.get("company_name"),
        pipeline_version=campaign.get("pipeline_version", "1.0.0"),
        summary=summary,
        created_at=campaign.get("created_at", ""),
        updated_at=campaign.get("updated_at", ""),
        completed_at=campaign.get("completed_at"),
        failure_reason=campaign.get("failure_reason"),
    )


def _build_icp_response(icp: Dict) -> ICPResponse:
    def _parse(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return []
        return val or []

    return ICPResponse(
        id=icp["id"],
        campaign_id=icp["campaign_id"],
        target_type=icp["target_type"],
        industry=_parse(icp.get("industry")),
        company_size_min=icp.get("company_size_min"),
        company_size_max=icp.get("company_size_max"),
        funding_status=_parse(icp.get("funding_status")) or None,
        job_titles=_parse(icp.get("job_titles")),
        seniority=_parse(icp.get("seniority")) or None,
        locations=_parse(icp.get("locations")),
        tech_stack=_parse(icp.get("tech_stack")) or None,
        demographics=icp.get("demographics"),
        confidence_score=icp.get("confidence_score"),
        missing_fields=_parse(icp.get("missing_fields")) or None,
        created_at=icp.get("created_at", ""),
        updated_at=icp.get("updated_at", ""),
    )


def _build_brief_response(brief: Dict) -> BriefResponse:
    def _parse(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return []
        return val or []

    return BriefResponse(
        id=brief["id"],
        campaign_id=brief["campaign_id"],
        product_name=brief["product_name"],
        what_it_does=brief["what_it_does"],
        who_it_is_for=brief["who_it_is_for"],
        pain_it_solves=brief["pain_it_solves"],
        key_differentiators=_parse(brief.get("key_differentiators")),
        ideal_customer_description=brief["ideal_customer_description"],
        created_at=brief.get("created_at", ""),
        updated_at=brief.get("updated_at", ""),
    )


async def _run_onboarding_background(campaign_id: str, user_id: str, website_url: str, company_name: Optional[str]):
    """Run onboarding agent in background after campaign is created."""
    print(f"[Campaigns] Running onboarding background for campaign {campaign_id}")
    try:
        from backend.core.pipeline_runner import PipelineRunner
        runner = PipelineRunner()
        await runner.run_onboarding(
            campaign_id=campaign_id,
            user_id=user_id,
            website_url=website_url,
            company_name=company_name,
        )
        logger.info(f"[Campaigns] Onboarding complete for campaign {campaign_id}")
    except Exception as e:
        logger.error(f"[Campaigns] Onboarding failed for campaign {campaign_id}: {e}")


# ── Campaign CRUD

@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignRequest,
    background_tasks: BackgroundTasks,
    user: Dict = Depends(require_active_subscription),
):
    """
    Create a new campaign and trigger onboarding agent in the background.
    Returns immediately with the created campaign — onboarding runs async.
    Poll GET /campaigns/{id}/pipeline/status to track progress.
    """
    db = get_db()

    campaign = db.create_campaign(
        user_id=user["id"],
        name=body.name,
        website_url=body.website_url,
        company_name=body.company_name,
    )

    # Provision orchestration slot immediately
    db.init_orchestration_state(campaign["id"], user["id"])
    print(f"[Campaigns] Initialized orchestration state for campaign {campaign['id']}")
    # Run onboarding in background
    background_tasks.add_task(
        _run_onboarding_background,
        campaign_id=campaign["id"],
        user_id=user["id"],
        website_url=body.website_url,
        company_name=body.company_name,
    )

    logger.info(f"[Campaigns] Created campaign {campaign['id']} for user {user['id']}")
    return _build_campaign_response(campaign, db)


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(user: Dict = Depends(get_current_user)):
    """List all campaigns for the authenticated user."""
    db = get_db()
    campaigns = db.get_campaigns_for_user(user["id"])
    return CampaignListResponse(
        campaigns=[_build_campaign_response(c, db) for c in campaigns],
        total=len(campaigns),
    )


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """Get a single campaign by ID."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)
    return _build_campaign_response(campaign, db)


@router.delete("/{campaign_id}", response_model=MessageResponse)
async def delete_campaign(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Cancel and delete a campaign.
    Sets status to CANCELLED. Does not delete leads or email sequences —
    those are preserved for audit purposes.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    # Prevent deleting a running campaign
    running_statuses = {
        CampaignStatus.ONBOARDING_RUNNING,
        CampaignStatus.INGESTION_RUNNING,
        CampaignStatus.ENRICHMENT_RUNNING,
        CampaignStatus.QUALIFICATION_RUNNING,
        CampaignStatus.EMAIL_GENERATION_RUNNING,
    }
    if campaign["status"] in {s.value for s in running_statuses}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a campaign while it is running. Wait for it to complete or fail.",
        )

    db.update_campaign_status(
        campaign_id=campaign_id,
        status=CampaignStatus.CANCELLED,
        agent="api",
        notes="Deleted by user via API.",
    )

    return MessageResponse(message=f"Campaign {campaign_id} cancelled successfully.")


# ── ICP

@router.get("/{campaign_id}/icp", response_model=ICPResponse)
async def get_icp(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """Get the ICP for a campaign."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    icp = db.get_icp(campaign_id)
    if not icp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICP not yet generated. Onboarding may still be running.",
        )
    return _build_icp_response(icp)


@router.put("/{campaign_id}/icp", response_model=ICPResponse)
async def update_icp(
    campaign_id: str,
    body: UpdateICPRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Update the ICP manually.
    Called when the user wants to edit the auto-generated ICP before running the pipeline.
    Only updates fields that are provided — partial update.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    existing = db.get_icp(campaign_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICP not found. Run onboarding first.",
        )

    # Merge: only update provided fields
    updates = body.model_dump(exclude_none=True)
    merged = {**existing, **updates}

    # Re-save as new ICP version
    db.save_icp(campaign_id, user["id"], merged)

    updated = db.get_icp(campaign_id)
    return _build_icp_response(updated)


# ── Product Brief

@router.get("/{campaign_id}/brief", response_model=BriefResponse)
async def get_brief(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """Get the product brief for a campaign."""
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    brief = db.get_product_brief(campaign_id)
    if not brief:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product brief not yet generated. Onboarding may still be running.",
        )
    return _build_brief_response(brief)


@router.put("/{campaign_id}/brief", response_model=BriefResponse)
async def update_brief(
    campaign_id: str,
    body: UpdateBriefRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Update the product brief manually.
    Partial update — only provided fields are changed.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    existing = db.get_product_brief(campaign_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product brief not found. Run onboarding first.",
        )

    updates = body.model_dump(exclude_none=True)
    merged = {**existing, **updates}
    db.save_product_brief(campaign_id, user["id"], merged)

    updated = db.get_product_brief(campaign_id)
    return _build_brief_response(updated)
