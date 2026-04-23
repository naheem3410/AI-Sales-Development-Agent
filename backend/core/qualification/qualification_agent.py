import asyncio
import logging
from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.enrichment.enrichment_agent import LeadEnrichmentResult, LeadEnrichmentAgentOutput
from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput
from backend.core.observability import agent_observe
from backend.core.qualification.instruction import QUALIFICATION_INSTRUCTIONS
from backend.core.utils.llm_batch import MAX_PARALLEL, async_run_with_retries, chunk_indices

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

    for lead, enrichment, gate in zip(leads, enrichments, gate_results):
        gi = enrichment.lead_index
        parts.append(f"\n--- Lead {gi} (global lead_index): {lead.name or enrichment.lead_name} ---")
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
        "\nReturn one LeadDecision per lead above (use each lead's global lead_index field), "
        "in lead_index order, grouped into approved/review/rejected lists.",
    ]

    return "\n".join(parts)


async def _run_qualification_llm_batch(
    leads: List[LeadResult],
    enrichments: List[LeadEnrichmentResult],
    gate_results: List[HardGateResult],
    onboarding: OnboardingAgentOutput,
) -> QualificationBatchOutput:
    model = LitellmModel(model="openai/gpt-4.1")

    with trace("qualification_agent"):
        agent = Agent(
            name="QualificationAgent",
            instructions=QUALIFICATION_INSTRUCTIONS,
            model=model,
            output_type=QualificationBatchOutput,
        )

        prompt = _build_qualification_prompt(leads, enrichments, onboarding, gate_results)

        logger.info(f"[QualificationAgent] Starting LLM scoring for {len(leads)} leads in batch.")
        try:
            result = await Runner.run(agent, prompt, max_turns=5)
        except MaxTurnsExceeded:
            logger.error("[QualificationAgent] Max turns exceeded.")
            raise

    if isinstance(result.final_output, str):
        output = QualificationBatchOutput.model_validate_json(result.final_output)
    else:
        output = QualificationBatchOutput.model_validate(result.final_output)

    batch_decisions = len(output.approved) + len(output.review) + len(output.rejected)
    if batch_decisions != len(leads):
        logger.warning(
            f"[QualificationAgent] Batch output has {batch_decisions} decisions for {len(leads)} leads."
        )

    return output


@agent_observe("qualification_agent", as_type="agent")
async def run_qualification_agent(
    leads: List[LeadResult],
    enrichment_output: LeadEnrichmentAgentOutput,
    onboarding: OnboardingAgentOutput,
) -> QualificationBatchOutput:

    n_leads = len(leads)
    if len(enrichment_output.enriched_leads) > n_leads:
        raise ValueError(
            f"More enrichments than leads: {len(enrichment_output.enriched_leads)} enrichments "
            f"for {n_leads} leads."
        )

    by_index: Dict[int, LeadEnrichmentResult] = {}
    for e in enrichment_output.enriched_leads:
        if 1 <= e.lead_index <= n_leads:
            by_index[e.lead_index] = e
        else:
            logger.warning(
                f"[QualificationAgent] Skipping enrichment with out-of-range lead_index={e.lead_index}"
            )

    ordered_keys = sorted(by_index.keys())
    matched_leads = [leads[i - 1] for i in ordered_keys]
    matched_enrichments = [by_index[i] for i in ordered_keys]

    if not matched_leads:
        logger.warning("[QualificationAgent] No valid lead/enrichment pairs; returning empty output.")
        return QualificationBatchOutput(
            approved=[],
            review=[],
            rejected=[],
            batch_summary="No leads with valid enrichment to qualify.",
        )

    icp = onboarding.icp

    gate_results = [
        _run_hard_gates(lead, enrichment, icp)
        for lead, enrichment in zip(matched_leads, matched_enrichments)
    ]

    passed = sum(1 for g in gate_results if g.passed)
    failed = len(gate_results) - passed
    logger.info(
        f"[QualificationAgent] Hard gates: {passed} passed, {failed} failed "
        f"out of {len(matched_leads)} matched leads."
    )

    m = len(matched_leads)
    slices = chunk_indices(m)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def run_slice(
        start: int, end: int
    ) -> Tuple[int, int, Optional[QualificationBatchOutput]]:
        lb = matched_leads[start:end]
        eb = matched_enrichments[start:end]
        gb = gate_results[start:end]
        async with sem:
            try:
                out = await async_run_with_retries(
                    lambda: _run_qualification_llm_batch(lb, eb, gb, onboarding)
                )
                return (start, end, out)
            except Exception as e:
                logger.error(
                    f"[QualificationAgent] Batch [{start}:{end}] failed after retries: {e}"
                )
                return (start, end, None)

    tasks = [asyncio.create_task(run_slice(s, e)) for s, e in slices]
    resolved = await asyncio.gather(*tasks)
    resolved.sort(key=lambda x: x[0])

    output = QualificationBatchOutput(approved=[], review=[], rejected=[], batch_summary="")
    summaries: List[str] = []
    expected_decisions = 0

    for start, end, part in resolved:
        if part is None:
            continue
        expected_decisions += end - start
        output.approved.extend(part.approved)
        output.review.extend(part.review)
        output.rejected.extend(part.rejected)
        if part.batch_summary:
            summaries.append(part.batch_summary)

    output.batch_summary = "\n---\n".join(summaries) if summaries else ""

    total_out = len(output.approved) + len(output.review) + len(output.rejected)
    if total_out != expected_decisions:
        logger.warning(
            f"[QualificationAgent] Decision count {total_out} != expected {expected_decisions} "
            f"from successful batches."
        )

    failed_indices = {
        enrich.lead_index
        for enrich, gate in zip(matched_enrichments, gate_results)
        if not gate.passed
    }
    leaked = [d for d in output.approved if d.lead_index in failed_indices]
    if leaked:
        logger.error(
            f"[QualificationAgent] Hard-gate failures leaked into approved: "
            f"{[d.lead_name for d in leaked]}. Moving to rejected."
        )
        output.rejected.extend(leaked)
        output.approved = [d for d in output.approved if d.lead_index not in failed_indices]

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