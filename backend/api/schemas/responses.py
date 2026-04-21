"""
responses.py
------------
Pydantic models for all API responses.
What the frontend receives.
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel
from datetime import datetime


# ── Generic ───────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ── User ──────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    plan: str
    has_active_subscription: bool
    created_at: str


# ── ICP ───────────────────────────────────────────────────────────────────

class ICPResponse(BaseModel):
    id: str
    campaign_id: str
    target_type: str
    industry: List[str]
    company_size_min: Optional[int]
    company_size_max: Optional[int]
    funding_status: Optional[List[str]]
    job_titles: List[str]
    seniority: Optional[List[str]]
    locations: List[str]
    tech_stack: Optional[List[str]]
    demographics: Optional[str]
    confidence_score: Optional[float]
    missing_fields: Optional[List[str]]
    created_at: str
    updated_at: str


# ── Product Brief ──────────────────────────────────────────────────────────

class BriefResponse(BaseModel):
    id: str
    campaign_id: str
    product_name: str
    what_it_does: str
    who_it_is_for: str
    pain_it_solves: str
    key_differentiators: List[str]
    ideal_customer_description: str
    created_at: str
    updated_at: str


# ── Campaign ───────────────────────────────────────────────────────────────

class CampaignSummary(BaseModel):
    total_leads: int
    enriched: int
    approved: int
    review: int
    rejected: int
    emails_written: int


class CampaignResponse(BaseModel):
    id: str
    user_id: str
    name: str
    status: str
    website_url: Optional[str]
    company_name: Optional[str]
    pipeline_version: str
    summary: Optional[CampaignSummary]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    failure_reason: Optional[str]


class CampaignListResponse(BaseModel):
    campaigns: List[CampaignResponse]
    total: int


# ── Pipeline ───────────────────────────────────────────────────────────────

class PipelineStatusResponse(BaseModel):
    campaign_id: str
    status: str
    current_stage: Optional[str]
    summary: CampaignSummary
    failure_reason: Optional[str]
    is_running: bool
    is_complete: bool
    is_failed: bool


class PipelineRunResponse(BaseModel):
    campaign_id: str
    message: str
    status: str


# ── Leads ─────────────────────────────────────────────────────────────────

class EnrichmentSummary(BaseModel):
    identity_status: Optional[str]
    confidence_score: Optional[float]
    current_title: Optional[str]
    company_signals: Optional[List[Dict[str, str]]]
    notable_achievements: Optional[List[str]]
    discrepancies: Optional[List[Dict[str, Any]]]
    enrichment_summary: Optional[str]


class QualificationSummary(BaseModel):
    decision: Optional[str]
    icp_match_score: Optional[float]
    decision_reason: Optional[str]
    blocking_issues: Optional[List[str]]
    review_flags: Optional[List[str]]
    recommended_angle: Optional[str]


class LeadResponse(BaseModel):
    id: str
    campaign_id: str
    status: str
    name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    title: Optional[str]
    seniority: Optional[str]
    email: Optional[str]
    email_status: Optional[str]
    phone: Optional[str]
    company: Optional[str]
    company_size: Optional[int]
    industry: Optional[str]
    location: Optional[str]
    country: Optional[str]
    linkedin: Optional[str]
    provider: Optional[str]
    lead_type: Optional[str]
    enrichment: Optional[EnrichmentSummary]
    qualification: Optional[QualificationSummary]
    created_at: str
    updated_at: str


class LeadListResponse(BaseModel):
    leads: List[LeadResponse]
    total: int
    campaign_id: str


# ── Emails ────────────────────────────────────────────────────────────────

class EmailDetail(BaseModel):
    subject: Optional[str]
    body: Optional[str]


class EmailSequenceResponse(BaseModel):
    id: str
    lead_id: str
    campaign_id: str
    lead_name: Optional[str]
    lead_email: str
    email_1: EmailDetail
    email_2: EmailDetail
    email_3: EmailDetail
    sequence_notes: Optional[str]
    email_1_sent_at: Optional[str]
    email_2_sent_at: Optional[str]
    email_3_sent_at: Optional[str]
    created_at: str
    updated_at: str


class EmailListResponse(BaseModel):
    sequences: List[EmailSequenceResponse]
    total: int
    campaign_id: str


# ── Analytics ────────────────────────────────────────────────────────────

class AnalyticsSummaryResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    campaign_status: str
    total_leads: int
    enriched: int
    approved: int
    review: int
    rejected: int
    emails_written: int
    approval_rate: Optional[float]
    enrichment_rate: Optional[float]
