"""
messages.py
-----------
Standard message envelope for all inter-agent communication.
The envelope is identical in local and production.
Only the transport layer (file queue vs SQS) changes.

Every agent receives a PipelineMessage and returns a PipelineMessage.
The payload is the agent's output, serialised as a dict.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.enums import AgentName, QueueName, MessageStatus, CampaignStatus


# ── Orchestration Metadata 
# Provisioned now — empty until orchestration agent is activated.
class OrchestrationMetadata(BaseModel):
    decision: Optional[str] = Field(
        None,
        description="Orchestration decision made at this step (e.g. 'fetch_all', 'switch_provider', 'retry')."
    )
    provider_selected: Optional[str] = Field(
        None,
        description="Lead provider chosen by orchestration agent (apollo or prospeo)."
    )
    fetch_all: Optional[bool] = Field(
        None,
        description="Whether orchestration decided to fetch all pages or just page 1."
    )
    batch_quality_score: Optional[float] = Field(
        None,
        description="Quality score of the ingested batch assessed by orchestration (0.0-1.0)."
    )
    filters_relaxed: Optional[bool] = Field(
        None,
        description="Whether orchestration relaxed any ICP filters."
    )
    relaxed_fields: Optional[List[str]] = Field(
        None,
        description="Which ICP fields were relaxed (e.g. ['location', 'seniority'])."
    )
    retry_count: int = Field(
        0,
        description="Number of times orchestration has retried this step."
    )
    notes: Optional[str] = Field(
        None,
        description="Free-text notes from the orchestration agent."
    )


# ── Pipeline Error 
class PipelineError(BaseModel):
    error_type: str
    error_message: str
    agent: AgentName
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recoverable: bool = False
    retry_suggested: bool = False


# ── Core Message Envelope 
class PipelineMessage(BaseModel):
    # Identity
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID for this message."
    )
    correlation_id: str = Field(
        description="Ties all messages in a single campaign run together. Set once at pipeline start."
    )

    # Ownership — always scoped to user + campaign
    user_id: str = Field(description="ID of the user who owns this campaign.")
    campaign_id: str = Field(description="ID of the campaign this message belongs to.")

    # Routing
    source_agent: AgentName = Field(description="Agent that produced this message.")
    target_agent: AgentName = Field(description="Agent that should consume this message.")
    queue: QueueName = Field(description="Queue this message is placed on.")

    # Orchestration slot — empty until orchestration agent is active
    orchestration: OrchestrationMetadata = Field(
        default_factory=OrchestrationMetadata,
        description="Orchestration metadata. Populated by orchestration agent when active."
    )

    # State
    status: MessageStatus = Field(default=MessageStatus.PENDING)
    campaign_status_on_send: CampaignStatus = Field(
        description="Campaign status at the time this message was produced."
    )

    # Payload — the actual agent output
    payload: Dict[str, Any] = Field(
        description="Serialised output of the source agent. Schema depends on source_agent."
    )

    # Lifecycle tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Retry handling
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[PipelineError] = None

    # Audit
    pipeline_version: str = Field(
        default="1.0.0",
        description="Version of the pipeline that produced this message. For future migration handling."
    )

    def mark_processing(self) -> "PipelineMessage":
        self.status = MessageStatus.PROCESSING
        self.processed_at = datetime.now(timezone.utc)
        return self

    def mark_complete(self) -> "PipelineMessage":
        self.status = MessageStatus.COMPLETE
        self.completed_at = datetime.now(timezone.utc)
        return self

    def mark_failed(self, error: PipelineError) -> "PipelineMessage":
        self.status = MessageStatus.FAILED
        self.last_error = error
        self.retry_count += 1
        return self

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def to_dead_letter(self) -> "PipelineMessage":
        self.status = MessageStatus.DEAD
        self.queue = QueueName.DEAD_LETTER
        return self


# ── Typed Payload Schemas (one per agent handoff) 
# These define exactly what each agent puts in message.payload.
# Agents serialise these to dict before sending, deserialise on receipt.

class OnboardingPayload(BaseModel):
    """Payload produced by Onboarding Agent."""
    website_url: str
    company_name: Optional[str]
    icp: Dict[str, Any]                  # serialised ICPOutput
    product_brief: Dict[str, Any]        # serialised ProductBriefOutput
    confidence_score: float
    missing_fields: List[str]


class OrchestrationPayload(BaseModel):
    """
    Payload produced by Orchestration Agent.
    Provisioned — not populated until orchestration agent is active.
    For now the pipeline runner passes through the onboarding payload unchanged.
    """
    onboarding: Dict[str, Any]           # pass-through of OnboardingPayload
    provider_selected: str               # which lead provider to use
    fetch_all: bool                      # whether to fetch all pages
    enrich_mobile: bool                  # whether to enrich mobile numbers
    target_lead_count: int               # how many leads to aim for
    notes: Optional[str] = None


class IngestionPayload(BaseModel):
    """Payload produced by Lead Ingestion."""
    provider: str
    total_leads: int
    leads: List[Dict[str, Any]]          # serialised List[LeadResult]
    fetch_all_used: bool
    pages_fetched: int


class QueryGeneratorPayload(BaseModel):
    """Payload produced by Query Generator."""
    total_leads: int
    query_results: List[Dict[str, Any]]  # serialised QueryGeneratorOutput.results


class EnrichmentPayload(BaseModel):
    """Payload produced by Enrichment Agent."""
    total_enriched: int
    enriched_leads: List[Dict[str, Any]] # serialised LeadEnrichmentAgentOutput.enriched_leads


class QualificationPayload(BaseModel):
    """Payload produced by Qualification Agent."""
    total_approved: int
    total_review: int
    total_rejected: int
    approved: List[Dict[str, Any]]
    review: List[Dict[str, Any]]
    rejected: List[Dict[str, Any]]
    batch_summary: str


class EmailPayload(BaseModel):
    """Payload produced by Email Agent."""
    total_sequences: int
    sequences: List[Dict[str, Any]]      # serialised List[EmailSequence]
    batch_notes: str


# ── Future Agent Payload Slots 
# Provisioned empty — fill in when agents are built.

class ReplyPayload(BaseModel):
    """Future: Reply Agent payload."""
    pass


class FollowUpPayload(BaseModel):
    """Future: Follow Up Agent payload."""
    pass


class MeetingPayload(BaseModel):
    """Future: Meeting Booking Agent payload."""
    pass


class CRMSyncPayload(BaseModel):
    """Future: CRM Sync Agent payload."""
    pass


class NurturePayload(BaseModel):
    """Future: Nurture Agent payload."""
    pass
