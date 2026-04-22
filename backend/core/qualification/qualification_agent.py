import asyncio
import logging
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.enrichment.enrichment_agent import LeadEnrichmentResult, LeadEnrichmentAgentOutput
from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Output models

class DimensionScore(BaseModel):
    dimension: Literal[
        "industry", "job_title", "seniority",
        "location", "company_size", "type_alignment", "pain_relevance"
    ]
    score: float = Field(ge=0.0, le=1.0, description="0.0 = no match, 1.0 = perfect match.")
    note: str = Field(description="One sentence explaining the score.")


class LeadDecision(BaseModel):
    lead_index: int = Field(description="1-based index matching the input list order.")
    lead_name: str
    decision: Literal["approved", "review", "rejected"]
    decision_reason: str = Field(description="One concise sentence explaining the primary factor behind the decision.")
    icp_match_score: float = Field(ge=0.0, le=1.0, description="Overall ICP fit score across all dimensions.")
    match_breakdown: List[DimensionScore] = Field(description="Per-dimension scores explaining the overall icp_match_score.")
    blocking_issues: List[str] = Field(
        default_factory=list,
        description="Hard blockers that caused rejection regardless of ICP fit (e.g. no email, not_found identity, type mismatch)."
    )
    review_flags: List[str] = Field(
        default_factory=list,
        description="Soft concerns requiring human review (e.g. discrepancies, low enrichment confidence, company size outside range)."
    )
    recommended_angle: Optional[str] = Field(
        None,
        description="Only for approved leads: which product pain point or differentiator is most relevant to pitch to this specific person."
    )


class QualificationBatchOutput(BaseModel):
    approved: List[LeadDecision] = Field(description="Leads cleared for email outreach.")
    review: List[LeadDecision] = Field(description="Leads that need human triage before sending.")
    rejected: List[LeadDecision] = Field(description="Leads that failed one or more hard gate criteria.")
    batch_summary: str = Field(description="Brief summary of batch quality, approval rate, and common rejection/review reasons.")


# Hard gate: Pure Python

class HardGateResult(BaseModel):
    passed: bool
    blocking_issues: List[str]
    review_flags: List[str]


def _run_hard_gates(
    lead: LeadResult,
    enrichment: LeadEnrichmentResult,
    icp: "ICPOutput", 
) -> HardGateResult:
    """
    Pure Python pre-filter. Any blocker here = rejected before LLM sees the lead.
    Review flags are passed through to the LLM for soft scoring context.
    """
    blocking_issues: List[str] = []
    review_flags: List[str] = []

    # Email must exist and be verified
    if not lead.email:
        blocking_issues.append("No email address available.")
    elif lead.email_status and lead.email_status.upper() != "VERIFIED":
        blocking_issues.append(f"Email status is '{lead.email_status}', not VERIFIED.")

    # Identity must be found
    if enrichment.identity_status == "not_found":
        blocking_issues.append("Identity could not be verified — no search results found.")

    # Enrichment confidence floor
    if enrichment.confidence_score < 0.3:
        blocking_issues.append(
            f"Enrichment confidence too low ({enrichment.confidence_score:.0%}) to trust lead data."
        )

    # Lead type vs ICP type alignment
    lead_type = lead.type or ("business" if lead.company or lead.title else "individual")
    icp_type = icp.target_type
    if icp_type != "both":
        if lead_type != "both" and lead_type != icp_type:
            blocking_issues.append(
                f"Lead type '{lead_type}' does not match ICP target type '{icp_type}'."
            )

    # Soft flags — do not block but pass to LLM
    if enrichment.identity_status == "ambiguous":
        review_flags.append("Identity is ambiguous — multiple people found with this name.")

    if enrichment.discrepancies:
        for d in enrichment.discrepancies:
            review_flags.append(
                f"Discrepancy on '{d.field}': provider says '{d.original_value}', "
                f"search found '{d.found_value}'."
            )

    if enrichment.confidence_score < 0.6:
        review_flags.append(
            f"Enrichment confidence is moderate ({enrichment.confidence_score:.0%}) — "
            f"some lead data may be inaccurate."
        )

    if icp.company_size_min is not None or icp.company_size_max is not None:
        size = lead.company_size
        if size is not None:
            if icp.company_size_min and size < icp.company_size_min:
                review_flags.append(
                    f"Company size ({size}) is below ICP minimum ({icp.company_size_min})."
                )
            if icp.company_size_max and size > icp.company_size_max:
                review_flags.append(
                    f"Company size ({size}) exceeds ICP maximum ({icp.company_size_max})."
                )
        else:
            review_flags.append("Company size unknown — could not verify against ICP range.")

    return HardGateResult(
        passed=len(blocking_issues) == 0,
        blocking_issues=blocking_issues,
        review_flags=review_flags,
    )


# Prompt builder

def _build_qualification_prompt(
    leads: List[LeadResult],
    enrichments: List[LeadEnrichmentResult],
    onboarding: OnboardingAgentOutput,
    gate_results: List[HardGateResult],
) -> str:
    icp = onboarding.icp
    brief = onboarding.product_brief

    parts = [
        "You are qualifying leads for email outreach. Score each lead against the ICP and product brief.\n",
        "Only evaluate leads that PASSED hard gates. Rejected leads are pre-decided — just format their output.\n\n",

        "== PRODUCT BRIEF ==",
        f"Product: {brief.product_name}",
        f"What it does: {brief.what_it_does}",
        f"Who it's for: {brief.who_it_is_for}",
        f"Pain it solves: {brief.pain_it_solves}",
        f"Differentiators: {', '.join(brief.key_differentiators)}",
        f"Ideal customer: {brief.ideal_customer_description}\n",

        "== ICP ==",
        f"Target type: {icp.target_type}",
        f"Industries: {', '.join(icp.industry)}",
        f"Job titles: {', '.join(icp.job_titles)}",
        f"Seniority: {', '.join(icp.seniority) if icp.seniority else 'not specified'}",
        f"Locations: {', '.join(icp.locations)}",
    ]

    if icp.company_size_min or icp.company_size_max:
        parts.append(f"Company size: {icp.company_size_min or 0} – {icp.company_size_max or 'unlimited'}")
    if icp.funding_status:
        parts.append(f"Funding stage: {', '.join(icp.funding_status)}")
    if icp.tech_stack:
        parts.append(f"Tech stack: {', '.join(icp.tech_stack)}")
    if icp.demographics:
        parts.append(f"Demographics: {icp.demographics}")

    parts.append("\n== LEADS TO QUALIFY ==")

    for i, (lead, enrichment, gate) in enumerate(zip(leads, enrichments, gate_results), 1):
        parts.append(f"\n--- Lead {i}: {lead.name or enrichment.lead_name} ---")
        parts.append(f"Hard gate: {'PASSED' if gate.passed else 'FAILED'}")

        if gate.blocking_issues:
            parts.append(f"Blocking issues: {'; '.join(gate.blocking_issues)}")
        if gate.review_flags:
            parts.append(f"Review flags: {'; '.join(gate.review_flags)}")

        # Raw lead data
        parts.append("[ Raw Lead Data ]")
        if lead.title:
            parts.append(f"  Title: {lead.title}")
        if lead.company:
            parts.append(f"  Company: {lead.company}")
        if lead.industry:
            parts.append(f"  Industry: {lead.industry}")
        if lead.seniority:
            parts.append(f"  Seniority: {lead.seniority}")
        if lead.company_size:
            parts.append(f"  Company size: {lead.company_size}")
        if lead.location:
            parts.append(f"  Location: {lead.location}, {lead.country or ''}")
        if lead.type:
            parts.append(f"  Lead type: {lead.type}")

        # Enriched data
        parts.append("[ Enriched Data ]")
        parts.append(f"  Identity status: {enrichment.identity_status}")
        parts.append(f"  Enrichment confidence: {enrichment.confidence_score:.0%}")
        if enrichment.enriched_data.current_title:
            parts.append(f"  Verified title: {enrichment.enriched_data.current_title}")
        if enrichment.enriched_data.company_signals:
            for sig in enrichment.enriched_data.company_signals:
                parts.append(f"  {sig.key}: {sig.value}")
        if enrichment.enriched_data.notable_achievements:
            parts.append(f"  Achievements: {'; '.join(enrichment.enriched_data.notable_achievements)}")
        parts.append(f"  Summary: {enrichment.enrichment_summary}")

    parts += [
        "\n== SCORING INSTRUCTIONS ==",
        "For each lead that PASSED hard gates:",
        "1. Score each dimension (industry, job_title, seniority, location, company_size, type_alignment, pain_relevance) 0.0–1.0.",
        "2. Compute icp_match_score as weighted average:",
        "   pain_relevance: 0.30, job_title: 0.25, industry: 0.20, seniority: 0.10, location: 0.10, company_size: 0.05.",
        "   type_alignment is a gate not a score — if misaligned it should already be a blocker.",
        "3. Decision thresholds:",
        "   icp_match_score >= 0.75 AND no review_flags → approved",
        "   icp_match_score >= 0.75 AND review_flags present → review",
        "   icp_match_score < 0.75 AND >= 0.50 → review",
        "   icp_match_score < 0.50 → rejected",
        "4. For approved leads only: write recommended_angle — one sentence on which pain point",
        "   or differentiator from the product brief maps best to this person's specific role and context.",
        "5. For FAILED hard gate leads: decision=rejected, icp_match_score=0.0,",
        "   copy blocking_issues as-is, skip dimension scoring and recommended_angle.",
        "6. Infer seniority from enriched title if LeadResult.seniority is null.",
        "7. Use enriched current_title over raw title for job_title and pain_relevance scoring.",
        "\nReturn one LeadDecision per lead, in input order, grouped into approved/review/rejected lists.",
    ]

    return "\n".join(parts)


# Instructions

QUALIFICATION_INSTRUCTIONS = """
You are a Lead Qualification Specialist. Your job is to score leads against an ICP and 
product brief, and decide whether each lead should be approved for email outreach, 
sent for human review, or rejected.

CRITICAL RULES:
- Leads that FAILED hard gates are always decision=rejected with icp_match_score=0.0.
  Do not re-evaluate them — copy their blocking_issues and move on.
- For passed leads, score all 7 dimensions honestly. Do not inflate scores.
- pain_relevance is the most important dimension (weight 0.30). Ask: would this person
  feel the pain described in the product brief given their specific role and company context?
- Use the enriched current_title over the raw title wherever available.
- Infer seniority from the enriched title if LeadResult.seniority is null.
- recommended_angle is ONLY for approved leads. It must reference a specific pain point
  or differentiator from the product brief, tailored to this person's context.
- Never hallucinate company signals or achievements not present in enriched data.
- Return all leads in input order, grouped into approved/review/rejected lists.
"""


# Agent runner

async def run_qualification_agent(
    leads: List[LeadResult],
    enrichment_output: LeadEnrichmentAgentOutput,
    onboarding: OnboardingAgentOutput,
) -> QualificationBatchOutput:

    if len(leads) != len(enrichment_output.enriched_leads):
        raise ValueError(
            f"Mismatch: {len(leads)} leads but {len(enrichment_output.enriched_leads)} enrichment results."
        )

    enrichments = enrichment_output.enriched_leads
    icp = onboarding.icp

    #Python hard gates — no LLM needed
    gate_results = [
        _run_hard_gates(lead, enrichment, icp)
        for lead, enrichment in zip(leads, enrichments)
    ]

    passed = sum(1 for g in gate_results if g.passed)
    failed = len(gate_results) - passed
    logger.info(
        f"[QualificationAgent] Hard gates: {passed} passed, {failed} failed "
        f"out of {len(leads)} leads."
    )

    # LLM soft scoring for passed leads + formatting for all
    model = LitellmModel(model="openai/gpt-4.1")

    with trace("qualification_agent"):
        agent = Agent(
            name="QualificationAgent",
            instructions=QUALIFICATION_INSTRUCTIONS,
            model=model,
            output_type=QualificationBatchOutput,
        )

        prompt = _build_qualification_prompt(leads, enrichments, onboarding, gate_results)

        logger.info(f"[QualificationAgent] Starting LLM scoring for {len(leads)} leads.")
        try:
            result = await Runner.run(agent, prompt, max_turns=5)
        except MaxTurnsExceeded:
            logger.error("[QualificationAgent] Max turns exceeded.")
            raise

    if isinstance(result.final_output, str):
        output = QualificationBatchOutput.model_validate_json(result.final_output)
    else:
        output = QualificationBatchOutput.model_validate(result.final_output)

    # Post-validation
    total_out = len(output.approved) + len(output.review) + len(output.rejected)
    if total_out != len(leads):
        raise ValueError(
            f"Output count mismatch: got {total_out} decisions for {len(leads)} leads."
        )

    # Ensure hard-failed leads are never in approved
    failed_names = {
        leads[i].name
        for i, g in enumerate(gate_results)
        if not g.passed
    }
    leaked = [d for d in output.approved if d.lead_name in failed_names]
    if leaked:
        logger.error(
            f"[QualificationAgent] Hard-gate failures leaked into approved: "
            f"{[d.lead_name for d in leaked]}. Moving to rejected."
        )
        output.rejected.extend(leaked)
        output.approved = [d for d in output.approved if d.lead_name not in failed_names]

    # Ensure approved leads have recommended_angle
    for decision in output.approved:
        if not decision.recommended_angle:
            logger.warning(
                f"[QualificationAgent] Approved lead '{decision.lead_name}' "
                f"missing recommended_angle — flagging for review."
            )
            decision.review_flags.append("Missing recommended_angle — needs manual pitch angle.")
            output.review.append(decision)
    output.approved = [d for d in output.approved if d.recommended_angle]

    # Log summary
    logger.info(
        f"[QualificationAgent] Final: {len(output.approved)} approved, "
        f"{len(output.review)} review, {len(output.rejected)} rejected."
    )

    return output


# Test main

if __name__ == "__main__":
    from core.mock_data import MOCK_ENRICHED_LEADS, MOCK_ENRICHMENT_OUTPUT, MOCK_ONBOARDING_ANDELA

    # Mock OnboardingAgentOutput
    from core.onboarding.onboarding_agent import ICPOutput, ProductBriefOutput

    mock_onboarding = OnboardingAgentOutput(
        icp=ICPOutput(
            target_type="business",
            industry=["Financial Services", "Software Development", "IT Services and IT Consulting"],
            company_size_min=50,
            company_size_max=10000,
            funding_status=None,
            job_titles=["Product Manager", "VP of Product", "Head of Product", "CTO", "Director of Product"],
            locations=["United States", "United Kingdom", "India", "Europe"],
            tech_stack=None,
            demographics=None,
            seniority=["manager", "director", "vp", "c_suite", "head"],
        ),
        product_brief=ProductBriefOutput(
            product_name="FlowMetrics",
            what_it_does="AI-powered product analytics platform that surfaces actionable insights from user behavior data.",
            who_it_is_for="Product managers and product leaders at mid-market SaaS and fintech companies.",
            pain_it_solves="Product teams waste hours manually querying data warehouses and building dashboards — they lack real-time, role-specific insights to make fast decisions.",
            key_differentiators=[
                "No-code setup — connects to existing data stack in under 30 minutes",
                "Role-based insight feeds tailored to PMs, engineers, and executives",
                "Automated anomaly detection with root-cause suggestions",
            ],
            ideal_customer_description=(
                "A product manager or product leader at a 100–5000 person fintech or SaaS company "
                "who owns a product with active users, reports to a VP or C-suite, and is frustrated "
                "by slow data pipelines and generic dashboards that don't answer their specific questions."
            ),
        ),
        confidence_score=0.9,
        missing_fields=[],
    )

    async def main():
        print(f" Qualifying {len(MOCK_ENRICHED_LEADS)} leads...\n")
        try:
            output = await run_qualification_agent(
                leads=MOCK_ENRICHED_LEADS,
                enrichment_output=MOCK_ENRICHMENT_OUTPUT,
                onboarding=MOCK_ONBOARDING_ANDELA,
                # onboarding=mock_onboarding,
            )

            print("\n" + "=" * 80)
            print(" QUALIFICATION REPORT")
            print("=" * 80)

            def print_decision(d: LeadDecision):
                icon = {"approved": "✅", "review": "⚠️", "rejected": "❌"}[d.decision]
                print(f"\n{icon} Lead {d.lead_index}: {d.lead_name}  [ICP fit: {d.icp_match_score:.0%}]")
                print(f"   Decision: {d.decision_reason}")
                if d.match_breakdown:
                    print("   Scores:")
                    for dim in d.match_breakdown:
                        print(f"     {dim.dimension}: {dim.score:.0%} — {dim.note}")
                if d.blocking_issues:
                    print(f"    Blockers: {'; '.join(d.blocking_issues)}")
                if d.review_flags:
                    print(f"   Flags: {'; '.join(d.review_flags)}")
                if d.recommended_angle:
                    print(f"   Pitch angle: {d.recommended_angle}")

            print(f"\n APPROVED ({len(output.approved)})")
            for d in output.approved:
                print_decision(d)

            print(f"\n  REVIEW ({len(output.review)})")
            for d in output.review:
                print_decision(d)

            print(f"\n REJECTED ({len(output.rejected)})")
            for d in output.rejected:
                print_decision(d)

            print(f"\n Batch summary: {output.batch_summary}")

        except Exception as e:
            print(f" Qualification failed: {e}")
            raise

    asyncio.run(main())