"""Shared Pydantic models for onboarding (Playwright, Fetch MCP, orchestrator)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class OnboardingAgentInput(BaseModel):
    website_url: str = Field(..., description="The full URL of the company website to analyze.")
    company_name: Optional[str] = Field(None, description="The name of the company, if known.")


class ICPOutput(BaseModel):
    target_type: Literal["business", "individual", "both"] = Field(
        ...,
        description="Whether the ICP targets companies or direct consumers.",
    )
    industry: List[str] = Field(
        ...,
        description="Relevant industry sectors. Use these exact values: "
        "'Software Development', 'IT Services and IT Consulting', "
        "'Technology, Information and Internet', 'Financial Services', "
        "'Hospitals and Health Care', 'Data Infrastructure and Analytics', "
        "'Business Consulting and Services', 'Staffing and Recruiting', "
        "'Marketing Services', 'Renewable Energy'.",
    )
    company_size_min: Optional[int] = Field(None, description="Minimum employee count for target businesses.")
    company_size_max: Optional[int] = Field(None, description="Maximum employee count for target businesses.")
    funding_status: Optional[List[str]] = Field(None, description="Preferred funding stages (e.g., Series A, Seed).")
    job_titles: List[str] = Field(
        ...,
        description="Target job titles or roles (e.g., CTO, Marketing Manager, Freelancer).",
    )
    locations: List[str] = Field(
        ...,
        description="Geographic regions where the target customers are located.",
    )
    tech_stack: Optional[List[str]] = Field(None, description="Technologies the customer likely uses.")
    demographics: Optional[str] = Field(
        None,
        description="For individual targets: age range, interests, or specific behaviors.",
    )
    seniority: Optional[
        List[
            Literal[
                "owner",
                "founder",
                "c_suite",
                "partner",
                "vp",
                "head",
                "director",
                "manager",
                "senior",
                "entry",
                "intern",
            ]
        ]
    ] = Field(None, description="Seniority levels to target.")


class ProductBriefOutput(BaseModel):
    product_name: str = Field(..., description="The official name of the product or service.")
    what_it_does: str = Field(..., description="A concise summary of the product's primary function.")
    who_it_is_for: str = Field(..., description="The primary audience or user persona.")
    pain_it_solves: str = Field(..., description="The specific problems or 'pain points' addressed.")
    key_differentiators: List[str] = Field(
        ...,
        description="Unique selling points that set it apart from competitors.",
    )
    ideal_customer_description: str = Field(
        ...,
        description="A narrative description of the perfect customer match.",
    )


class OnboardingAgentOutput(BaseModel):
    icp: ICPOutput
    product_brief: ProductBriefOutput
    confidence_score: float = Field(..., description="Score between 0-1 reflecting data completeness.")
    missing_fields: List[str] = Field(
        ...,
        description="List of fields that couldn't be determined from the website.",
    )
