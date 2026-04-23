"""
pipeline.py
-----------
Pipeline control endpoints:
  POST /campaigns/{campaign_id}/pipeline/run      trigger full pipeline
  GET  /campaigns/{campaign_id}/pipeline/status   poll current status
"""

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from backend.api.dependencies.auth import (
    get_current_user,
    require_active_subscription,
    verify_campaign_ownership,
)
from backend.api.schemas.requests import RunPipelineRequest
from backend.api.schemas.responses import PipelineStatusResponse, PipelineRunResponse, CampaignSummary
from backend.infrastructure.factory import get_db
from backend.core.enums import CampaignStatus
from backend.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pipeline"])

# Statuses that mean the pipeline is actively running
RUNNING_STATUSES = {
    CampaignStatus.ONBOARDING_RUNNING.value,
    CampaignStatus.ORCHESTRATION_RUNNING.value,
    CampaignStatus.INGESTION_RUNNING.value,
    CampaignStatus.ENRICHMENT_RUNNING.value,
    CampaignStatus.QUALIFICATION_RUNNING.value,
    CampaignStatus.EMAIL_GENERATION_RUNNING.value,
}

COMPLETE_STATUSES = {
    CampaignStatus.EMAIL_GENERATION_COMPLETE.value,
    CampaignStatus.CAMPAIGN_COMPLETE.value,
}

FAILED_STATUSES = {
    CampaignStatus.ONBOARDING_FAILED.value,
    CampaignStatus.ORCHESTRATION_FAILED.value,
    CampaignStatus.INGESTION_FAILED.value,
    CampaignStatus.ENRICHMENT_FAILED.value,
    CampaignStatus.QUALIFICATION_FAILED.value,
    CampaignStatus.EMAIL_GENERATION_FAILED.value,
    CampaignStatus.FAILED.value,
}

# What stage a status belongs to — for frontend display
STATUS_STAGE_MAP = {
    CampaignStatus.CREATED.value: "setup",
    CampaignStatus.ONBOARDING_RUNNING.value: "onboarding",
    CampaignStatus.ONBOARDING_COMPLETE.value: "onboarding",
    CampaignStatus.ORCHESTRATION_RUNNING.value: "orchestration",
    CampaignStatus.ORCHESTRATION_COMPLETE.value: "orchestration",
    CampaignStatus.INGESTION_RUNNING.value: "ingestion",
    CampaignStatus.INGESTION_COMPLETE.value: "ingestion",
    CampaignStatus.ENRICHMENT_RUNNING.value: "enrichment",
    CampaignStatus.ENRICHMENT_COMPLETE.value: "enrichment",
    CampaignStatus.QUALIFICATION_RUNNING.value: "qualification",
    CampaignStatus.QUALIFICATION_COMPLETE.value: "qualification",
    CampaignStatus.EMAIL_GENERATION_RUNNING.value: "email_generation",
    CampaignStatus.EMAIL_GENERATION_COMPLETE.value: "email_generation",
    CampaignStatus.CAMPAIGN_COMPLETE.value: "complete",
}


# ── Background Task

async def _run_pipeline_background(
    campaign_id: str,
    user_id: str,
    provider: str,
    fetch_all: bool,
    enrich_mobile: bool,
    target_lead_count: int,
):
    """
    Runs the full pipeline asynchronously.
    In local mode: runs in-process as a background task.
    In production: this would instead push a message to SQS
                   and Lambda would pick it up.
    """
    try:
        from backend.core.pipeline_runner import PipelineRunner
        runner = PipelineRunner()

        # Get campaign for website_url and company_name
        db = get_db()
        campaign = db.get_campaign(campaign_id)

        # Run onboarding pass-through (onboarding already ran on campaign creation)
        # Build the orchestration pass-through message from existing DB state
        from backend.core.messages import PipelineMessage, OnboardingPayload
        from backend.core.enums import AgentName, QueueName
        import uuid

        icp_data = db.get_icp(campaign_id)
        brief_data = db.get_product_brief(campaign_id)

        if not icp_data or not brief_data:
            raise ValueError(
                "ICP and product brief must exist before running pipeline. "
                "Wait for onboarding to complete."
            )

        # Construct a synthetic onboarding message from DB state
        onboarding_payload = OnboardingPayload(
            website_url=campaign.get("website_url", ""),
            company_name=campaign.get("company_name"),
            icp=icp_data,
            product_brief=brief_data,
            confidence_score=icp_data.get("confidence_score", 1.0),
            missing_fields=icp_data.get("missing_fields") or [],
        )

        onboarding_msg = PipelineMessage(
            correlation_id=str(uuid.uuid4()),
            user_id=user_id,
            campaign_id=campaign_id,
            source_agent=AgentName.ONBOARDING,
            target_agent=AgentName.ORCHESTRATION,
            queue=QueueName.ONBOARDING_COMPLETE,
            campaign_status_on_send=CampaignStatus.ONBOARDING_COMPLETE,
            payload=onboarding_payload.model_dump(),
        )

        # Orchestration pass-through
        orch_msg = runner.run_orchestration_passthrough(
            onboarding_message=onboarding_msg,
            provider=provider,
            fetch_all=fetch_all,
            enrich_mobile=enrich_mobile,
            target_lead_count=target_lead_count,
        )

        # Ingestion
        ingestion_msg = runner.run_ingestion(orch_msg)

        # Enrichment (includes query generation)
        enrichment_msg = await runner.run_enrichment(ingestion_msg)

        # Qualification
        qualification_msg = await runner.run_qualification(enrichment_msg)

        # Email generation
        await runner.run_email_generation(qualification_msg)

        # Mark complete
        db.update_campaign_status(
            campaign_id=campaign_id,
            status=CampaignStatus.CAMPAIGN_COMPLETE,
            agent=AgentName.EMAIL.value,
            notes="Pipeline completed successfully.",
        )

        logger.info(f"[Pipeline] Campaign {campaign_id} completed successfully.")

    except Exception as e:
        logger.error(f"[Pipeline] Campaign {campaign_id} failed: {e}")
        try:
            db = get_db()
            db.update_campaign_status(
                campaign_id=campaign_id,
                status=CampaignStatus.FAILED,
                failure_reason=str(e),
                agent="pipeline_runner",
            )
        except Exception as db_err:
            logger.error(f"[Pipeline] Failed to update campaign status: {db_err}")


async def _run_pipeline_production(
    campaign_id: str,
    user_id: str,
    provider: str,
    fetch_all: bool,
    enrich_mobile: bool,
    target_lead_count: int,
):
    """
    Production mode: push pipeline start message to SQS.
    Lambda picks it up and runs each step.
    """
    from backend.infrastructure.factory import get_queue
    from backend.core.messages import PipelineMessage, OnboardingPayload
    from backend.core.enums import AgentName, QueueName
    import uuid

    db = get_db()
    queue = get_queue()

    icp_data = db.get_icp(campaign_id)
    brief_data = db.get_product_brief(campaign_id)

    onboarding_payload = OnboardingPayload(
        website_url=db.get_campaign(campaign_id).get("website_url", ""),
        company_name=db.get_campaign(campaign_id).get("company_name"),
        icp=icp_data,
        product_brief=brief_data,
        confidence_score=icp_data.get("confidence_score", 1.0),
        missing_fields=icp_data.get("missing_fields") or [],
    )

    message = PipelineMessage(
        correlation_id=str(uuid.uuid4()),
        user_id=user_id,
        campaign_id=campaign_id,
        source_agent=AgentName.ONBOARDING,
        target_agent=AgentName.ORCHESTRATION,
        queue=QueueName.ONBOARDING_COMPLETE,
        campaign_status_on_send=CampaignStatus.ONBOARDING_COMPLETE,
        payload={
            **onboarding_payload.model_dump(),
            "provider": provider,
            "fetch_all": fetch_all,
            "enrich_mobile": enrich_mobile,
            "target_lead_count": target_lead_count,
        },
    )

    queue.send(message)
    logger.info(f"[Pipeline] Campaign {campaign_id} queued for production processing.")


# ── Endpoints

@router.post(
    "/campaigns/{campaign_id}/pipeline/run",
    response_model=PipelineRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_pipeline(
    campaign_id: str,
    body: RunPipelineRequest,
    background_tasks: BackgroundTasks,
    user: Dict = Depends(require_active_subscription),
):
    """
    Trigger the full pipeline for a campaign.
    Requires onboarding to be complete (ICP and brief must exist).

    Returns 202 Accepted immediately.
    The pipeline runs asynchronously — poll /pipeline/status to track progress.

    Local: runs in-process as a background task.
    Production: pushes to SQS, Lambda handles execution.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    # Guard: onboarding must be complete
    icp = db.get_icp(campaign_id)
    brief = db.get_product_brief(campaign_id)
    if not icp or not brief:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding is not complete. ICP and product brief must exist before running the pipeline.",
        )

    # Guard: cannot run while already running
    if campaign["status"] in RUNNING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pipeline is already running (status: {campaign['status']}). Wait for it to complete.",
        )

    # Guard: cannot run on cancelled campaign
    if campaign["status"] == CampaignStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Campaign is cancelled and cannot be restarted.",
        )

    # Route to local or production runner
    if settings.is_local():
        background_tasks.add_task(
            _run_pipeline_background,
            campaign_id=campaign_id,
            user_id=user["id"],
            provider=body.provider,
            fetch_all=body.fetch_all,
            enrich_mobile=body.enrich_mobile,
            target_lead_count=body.target_lead_count,
        )
    else:
        background_tasks.add_task(
            _run_pipeline_production,
            campaign_id=campaign_id,
            user_id=user["id"],
            provider=body.provider,
            fetch_all=body.fetch_all,
            enrich_mobile=body.enrich_mobile,
            target_lead_count=body.target_lead_count,
        )

    logger.info(f"[Pipeline] Triggered pipeline for campaign {campaign_id}")

    return PipelineRunResponse(
        campaign_id=campaign_id,
        message="Pipeline started. Poll /pipeline/status for progress.",
        status="queued",
    )


@router.get(
    "/campaigns/{campaign_id}/pipeline/status",
    response_model=PipelineStatusResponse,
)
async def get_pipeline_status(
    campaign_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Get the current pipeline status for a campaign.
    Frontend polls this endpoint to show real-time progress.
    Returns current stage, summary counts, and whether pipeline is running/complete/failed.
    """
    db = get_db()
    campaign = db.get_campaign(campaign_id)
    verify_campaign_ownership(campaign, user, campaign_id)

    campaign_status = campaign["status"]
    summary_raw = db.get_campaign_summary(campaign_id)

    return PipelineStatusResponse(
        campaign_id=campaign_id,
        status=campaign_status,
        current_stage=STATUS_STAGE_MAP.get(campaign_status),
        summary=CampaignSummary(**summary_raw),
        failure_reason=campaign.get("failure_reason"),
        is_running=campaign_status in RUNNING_STATUSES,
        is_complete=campaign_status in COMPLETE_STATUSES,
        is_failed=campaign_status in FAILED_STATUSES,
    )
