import logging
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Input model
class LeadResult(BaseModel):
    name: Optional[str] = Field(None, description="Full name of the lead.")
    first_name: Optional[str] = Field(None, description="First name of the lead.")
    last_name: Optional[str] = Field(None, description="Last name of the lead.")
    title: Optional[str] = Field(None, description="Current job title of the lead.")
    seniority: Optional[str] = Field(None, description="Seniority level of the lead (e.g., C-Suite, Director, Manager).")
    email: Optional[str] = Field(None, description="Work email address of the lead.")
    email_status: Optional[str] = Field(None, description="Email verification status (e.g., VERIFIED, UNVERIFIED).")
    phone: Optional[str] = Field(None, description="Mobile or direct phone number of the lead.")
    company: Optional[str] = Field(None, description="Name of the company the lead currently works at.")
    company_size: Optional[int] = Field(None, description="Number of employees at the lead's current company.")
    industry: Optional[str] = Field(None, description="Industry sector of the lead's current company.")
    location: Optional[str] = Field(None, description="City where the lead is located.")
    country: Optional[str] = Field(None, description="Country where the lead is located.")
    linkedin: Optional[str] = Field(None, description="LinkedIn profile URL of the lead.")
    provider_id: Optional[str] = Field(None, description="Unique ID assigned to the lead by the data provider.")
    provider: Optional[str] = Field(None, description="Data provider used to source this lead (e.g., prospeo, apollo).")
    type: Optional[str] = Field(None, description="Type of the lead (business, individual, both).")


# Output models
class LeadQueries(BaseModel):
    queries: List[str] = Field(
        description=(
            "Exactly 5 high-quality Google search queries designed to find and verify "
            "information about this specific lead. Queries should cover: (1) identity & LinkedIn "
            "presence, (2) current role & company, (3) professional background & news, "
            "(4) contact/email verification, (5) industry credibility or public mentions."
        ),
        min_length=5,
        max_length=5,
    )


class QueryGeneratorOutput(BaseModel):
    results: List[LeadQueries] = Field(
        description="One LeadQueries entry per lead, in the same order as the input list, each containing exactly 5 search queries."
    )


# Helpers
def _resolve_type(lead: LeadResult) -> str:
    if lead.type in ("business", "individual", "both"):
        return lead.type
    if lead.company or lead.title:
        return "business"
    return "individual"


def _resolve_name(lead: LeadResult) -> Optional[str]:
    """Best available display name."""
    if lead.name:
        return lead.name
    parts = [lead.first_name, lead.last_name]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _linkedin_handle(lead: LeadResult) -> Optional[str]:
    if not lead.linkedin:
        return None
    return lead.linkedin.rstrip("/").split("/")[-1]


def _q(value: str) -> str:
    """Wrap a value in double quotes for use in a search query."""
    return f'"{value}"'

def _fmt(v) -> str:
    """Format a value for error messages — quotes strings, bare None for null."""
    return f"'{v}'" if v is not None else "None"


# Query builders (one per slot)
def _build_q1(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Identity & LinkedIn."""
    handle = _linkedin_handle(lead)
    if handle and name:
        return f"site:linkedin.com/in/{handle} {_q(name)}"
    if not name:
        return None
    if resolved_type in ("business", "both") and lead.company:
        return f"{_q(name)} LinkedIn {_q(lead.company)}"
    if lead.location:
        return f"{_q(name)} LinkedIn {_q(lead.location)}"
    return f"{_q(name)} LinkedIn profile"

def _build_q1_fallback(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Fallback identity query when site: returns 0 — broader LinkedIn search."""
    if not name:
        return None
    if lead.company:
        return f"{_q(name)} LinkedIn {_q(lead.company)}"
    if lead.location:
        return f"{_q(name)} LinkedIn {_q(lead.location)}"
    return f"{_q(name)} LinkedIn profile"

def _build_q2(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Current role & company."""
    if not name:
        return None
    if resolved_type in ("business", "both"):
        if lead.title and lead.company:
            return f"{_q(name)} {_q(lead.title)} {_q(lead.company)}"
        if lead.company:
            return f"{_q(name)} {_q(lead.company)}"
        if lead.title:
            return f"{_q(name)} {_q(lead.title)}"
    if lead.location:
        return f"{_q(name)} {_q(lead.location)} occupation OR profession"
    return None


def _build_q3(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Professional background & news."""
    if not name:
        return None
    if resolved_type in ("business", "both") and lead.company:
        return f"{_q(name)} {_q(lead.company)} interview OR news OR announcement"
    if lead.location:
        return f"{_q(name)} {_q(lead.location)} news OR mention OR profile"
    return f"{_q(name)} interview OR news OR profile"


def _build_q4(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Contact & email verification."""
    if lead.email:
        return f"{_q(lead.email)} contact OR email"
    if not name:
        return None
    if resolved_type in ("business", "both") and lead.company:
        return f"{_q(name)} {_q(lead.company)} contact OR email"
    if lead.location:
        return f"{_q(name)} {_q(lead.location)} contact"
    return f"{_q(name)} contact OR email"


def _build_q5(name: Optional[str], lead: LeadResult, resolved_type: str) -> Optional[str]:
    """Credibility & public mentions."""
    if not name:
        return None
    if resolved_type in ("business", "both"):
        if lead.industry:
            return f"{_q(name)} speaker OR author OR podcast {_q(lead.industry)}"
        if lead.company:
            return f"{_q(name)} speaker OR author OR podcast {_q(lead.company)}"
    # individual or fallback
    if lead.location:
        return f"{_q(name)} review OR testimonial OR mention {_q(lead.location)}"
    return f"{_q(name)} review OR testimonial OR mention"


# Core builder
def _build_queries(lead: LeadResult) -> List[str]:
    name = _resolve_name(lead)
    resolved_type = _resolve_type(lead)

    slots = [
        _build_q1(name, lead, resolved_type),
        _build_q2(name, lead, resolved_type),
        _build_q3(name, lead, resolved_type),
        _build_q4(name, lead, resolved_type),
        _build_q5(name, lead, resolved_type),
    ]

    missing = [i + 1 for i, q in enumerate(slots) if q is None]
    if missing:
        raise ValueError(
            f"Could not build queries for slot(s) {missing} — "
            f"lead has insufficient data (name={_fmt(name)}, company={_fmt(lead.company)}, "
            f"location={_fmt(lead.location)}, email={_fmt(lead.email)})."
        )

    return slots 

# Main entry point
def generate_queries(leads: List[LeadResult]) -> QueryGeneratorOutput:
    results = []
    errors = []

    for i, lead in enumerate(leads, 1):
        try:
            queries = _build_queries(lead)
            results.append(LeadQueries(queries=queries))
        except ValueError as e:
            errors.append(f"Lead {i}: {e}")
            logger.warning(f"Skipping lead {i} — {e}")

    if errors:
        logger.warning(f"{len(errors)} lead(s) skipped due to insufficient data:\n" + "\n".join(errors))

    return QueryGeneratorOutput(results=results)