"""
enums.py
--------
All pipeline states, agent identifiers, queue names, and status codes.
Single source of truth — never hardcode these strings anywhere else.
"""

from enum import Enum


# ── Campaign / Pipeline States 
class CampaignStatus(str, Enum):
    # Setup
    CREATED = "created"
    ONBOARDING_RUNNING = "onboarding_running"
    ONBOARDING_COMPLETE = "onboarding_complete"
    ONBOARDING_FAILED = "onboarding_failed"

    # Orchestration (active later — slot provisioned now)
    ORCHESTRATION_RUNNING = "orchestration_running"
    ORCHESTRATION_COMPLETE = "orchestration_complete"
    ORCHESTRATION_FAILED = "orchestration_failed"

    # Lead Ingestion
    INGESTION_RUNNING = "ingestion_running"
    INGESTION_COMPLETE = "ingestion_complete"
    INGESTION_FAILED = "ingestion_failed"

    # Enrichment
    ENRICHMENT_RUNNING = "enrichment_running"
    ENRICHMENT_COMPLETE = "enrichment_complete"
    ENRICHMENT_FAILED = "enrichment_failed"

    # Qualification
    QUALIFICATION_RUNNING = "qualification_running"
    QUALIFICATION_COMPLETE = "qualification_complete"
    QUALIFICATION_FAILED = "qualification_failed"

    # Email Generation
    EMAIL_GENERATION_RUNNING = "email_generation_running"
    EMAIL_GENERATION_COMPLETE = "email_generation_complete"
    EMAIL_GENERATION_FAILED = "email_generation_failed"

    # Sending (future)
    EMAILS_SCHEDULED = "emails_scheduled"
    EMAILS_SENDING = "emails_sending"
    EMAILS_SENT = "emails_sent"

    # Reply handling (future)
    REPLIES_MONITORING = "replies_monitoring"
    REPLY_RECEIVED = "reply_received"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    FOLLOWUP_SENT = "followup_sent"
    MEETING_SCHEDULED = "meeting_scheduled"

    # Terminal states
    CAMPAIGN_COMPLETE = "campaign_complete"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Lead States 
class LeadStatus(str, Enum):
    INGESTED = "ingested"
    QUERIED = "queried"                  # queries generated
    ENRICHED = "enriched"
    ENRICHMENT_FAILED = "enrichment_failed"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    REVIEW = "review"
    EMAIL_WRITTEN = "email_written"
    EMAIL_SCHEDULED = "email_scheduled"  # future
    EMAIL_SENT = "email_sent"            # future

    # Outreach sequence & inbound replies (sender, scheduler, reply handler, APIs)
    ACTIVE = "active"                     # contact is in outbound sequence / engaged
    PAUSED = "paused"                     # follow-ups paused (OOO / manual resume)
    INACTIVE = "inactive"                 # sequence exhausted or thread closed — no outreach
    OUTREACH_REVIEW = "outreach_review"   # ambiguous reply — human queue
    DO_NOT_CONTACT = "do_not_contact"     # explicit opt-out
    TRANSFERRED = "transferred"           # referral passed to another contact
    CONVERTED = "converted"               # booked via Cal.com (or terminal win — see webhook)

    REPLIED = "replied"                  # inbound reply handled
    MEETING_BOOKED = "meeting_booked"    # future
    NURTURE = "nurture"                  # future
    UNSUBSCRIBED = "unsubscribed"        # future
    BOUNCED = "bounced"                  # future


# ── Agent Identifiers 
class AgentName(str, Enum):
    ONBOARDING = "onboarding_agent"
    ORCHESTRATION = "orchestration_agent"    # provisioned — not active yet
    INGESTION = "ingestion_agent"
    QUERY_GENERATOR = "query_generator"
    ENRICHMENT = "enrichment_agent"
    QUALIFICATION = "qualification_agent"
    EMAIL = "email_agent"
    REPLY = "reply_agent"                    # future
    FOLLOWUP = "followup_agent"              # future
    MEETING = "meeting_agent"                # future
    CRM_SYNC = "crm_sync_agent"              # future
    NURTURE = "nurture_agent"                # future


# ── Queue Names 
# Used as: folder names locally, SQS queue names in production
class QueueName(str, Enum):
    ONBOARDING_COMPLETE = "onboarding_complete"
    ORCHESTRATION_IN = "orchestration_in"        # provisioned
    ORCHESTRATION_OUT = "orchestration_out"      # provisioned
    INGESTION_COMPLETE = "ingestion_complete"
    ENRICHMENT_COMPLETE = "enrichment_complete"
    QUALIFICATION_COMPLETE = "qualification_complete"
    EMAIL_COMPLETE = "email_complete"
    REPLY_IN = "reply_in"                        # future
    FOLLOWUP_IN = "followup_in"                  # future
    MEETING_IN = "meeting_in"                    # future
    DEAD_LETTER = "dead_letter"


# ── Message Status 
class MessageStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    DEAD = "dead"            # moved to dead letter queue


# ── Lead Provider 
class LeadProvider(str, Enum):
    APOLLO = "apollo"
    PROSPEO = "prospeo"


# ── Lead Decision 
class QualificationDecision(str, Enum):
    APPROVED = "approved"
    REVIEW = "review"
    REJECTED = "rejected"


# ── Identity Status 
class IdentityStatus(str, Enum):
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
