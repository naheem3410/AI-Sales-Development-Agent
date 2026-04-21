"""
requests.py
-----------
Pydantic models for all incoming API request bodies.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, HttpUrl


# ── Campaigns ──────────────────────────────────────────────────────────────

class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="User-defined campaign name.")
    website_url: str = Field(..., description="Company website URL for onboarding agent to scrape.")
    company_name: Optional[str] = Field(None, description="Company name (optional — onboarding agent will infer if not provided).")
    provider: Optional[Literal["prospeo", "apollo"]] = Field("prospeo", description="Lead data provider to use.")
    fetch_all: Optional[bool] = Field(False, description="Fetch all pages of leads (True) or just first page (False).")
    enrich_mobile: Optional[bool] = Field(False, description="Enrich mobile phone numbers (costs more credits).")
    target_lead_count: Optional[int] = Field(25, ge=1, le=1000, description="Target number of leads to ingest.")


# ── ICP ───────────────────────────────────────────────────────────────────

class UpdateICPRequest(BaseModel):
    target_type: Optional[Literal["business", "individual", "both"]] = None
    industry: Optional[List[str]] = None
    company_size_min: Optional[int] = Field(None, ge=1)
    company_size_max: Optional[int] = Field(None, ge=1)
    funding_status: Optional[List[str]] = None
    job_titles: Optional[List[str]] = None
    seniority: Optional[List[Literal[
        "owner", "founder", "c_suite", "partner",
        "vp", "head", "director", "manager",
        "senior", "entry", "intern"
    ]]] = None
    locations: Optional[List[str]] = None
    tech_stack: Optional[List[str]] = None
    demographics: Optional[str] = None


# ── Product Brief ──────────────────────────────────────────────────────────

class UpdateBriefRequest(BaseModel):
    product_name: Optional[str] = None
    what_it_does: Optional[str] = None
    who_it_is_for: Optional[str] = None
    pain_it_solves: Optional[str] = None
    key_differentiators: Optional[List[str]] = None
    ideal_customer_description: Optional[str] = None


# ── Pipeline ───────────────────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    provider: Optional[Literal["prospeo", "apollo"]] = Field("prospeo")
    fetch_all: Optional[bool] = Field(False)
    enrich_mobile: Optional[bool] = Field(False)
    target_lead_count: Optional[int] = Field(25, ge=1, le=1000)


# ── Emails ────────────────────────────────────────────────────────────────

class UpdateEmailRequest(BaseModel):
    email_1_subject: Optional[str] = None
    email_1_body: Optional[str] = None
    email_2_subject: Optional[str] = None
    email_2_body: Optional[str] = None
    email_3_subject: Optional[str] = None
    email_3_body: Optional[str] = None
