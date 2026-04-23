# email_agent.py

import asyncio
import logging
import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.enrichment.enrichment_agent import LeadEnrichmentResult
from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput
from backend.core.outreach.rag.intelligent_retrieval import retrieve_sequence_rag_context
from backend.core.qualification.qualification_agent import LeadDecision
from backend.core.observability import agent_observe
from backend.core.email.instruction import COPYWRITING_INSTRUCTIONS
from backend.core.utils.llm_batch import MAX_PARALLEL, async_run_with_retries, chunk_indices

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mustache-style tokens the model must not leave in final copy; unresolved keys are stripped.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

_PLACEHOLDER_KEY_ALIASES = {
    "sender": "sender_name",
    "firstname": "first_name",
    "first_name": "first_name",
    "lastname": "last_name",
    "companyname": "company_name",
    "lead": "lead_name",
    "prospect": "first_name",
    "prospect_name": "first_name",
    "recipient": "first_name",
    "product": "product_name",
}


def _canonical_placeholder_key(raw: str) -> str:
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return _PLACEHOLDER_KEY_ALIASES.get(key, key)


def _first_token(name: Optional[str]) -> Optional[str]:
    if not name or not str(name).strip():
        return None
    return str(name).strip().split()[0]


def build_substitution_vars(
    lead: LeadResult,
    onboarding: OnboardingAgentOutput,
    sender_display_name: Optional[str],
    verified_title: Optional[str],
) -> Dict[str, str]:
    """Non-empty strings only — used to replace tokens; missing keys drop the placeholder."""
    out: Dict[str, str] = {}

    sender_first = _first_token(sender_display_name)
    if sender_first:
        out["sender_name"] = sender_first
        parts = str(sender_display_name).strip().split()
        if len(parts) > 1:
            out["sender_last_name"] = parts[-1]

    fn = (lead.first_name or "").strip()
    if not fn and lead.name:
        fn = _first_token(lead.name) or ""
    if fn:
        out["first_name"] = fn
        out["name"] = fn

    ln = (lead.last_name or "").strip()
    if ln:
        out["last_name"] = ln

    if lead.name and lead.name.strip():
        out["lead_name"] = lead.name.strip()

    if lead.company and str(lead.company).strip():
        c = str(lead.company).strip()
        out["company"] = c
        out["company_name"] = c

    if verified_title and str(verified_title).strip():
        out["title"] = str(verified_title).strip()

    pn = onboarding.product_brief.product_name
    if pn and str(pn).strip():
        out["product_name"] = str(pn).strip()

    return out


def sanitize_email_text(text: str, variables: Dict[str, str]) -> str:
    """Replace {{key}} with variables when defined; remove token when value missing."""

    def _repl(match: re.Match[str]) -> str:
        canon = _canonical_placeholder_key(match.group(1))
        val = variables.get(canon)
        return val if val else ""

    out = _PLACEHOLDER_RE.sub(_repl, text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


class Email(BaseModel):
    subject: str = Field(description="Email subject line. Specific, curiosity-driven, never generic.")
    body: str = Field(description="Full email body in plain text. No HTML.")


class EmailSequence(BaseModel):
    lead_index: int
    lead_name: str
    lead_email: str
    email_1: Email = Field(
        description=(
            "Short, personalised cold outreach. 3–5 sentences max. "
            "Opens with a specific observation about the prospect or their company — "
            "drawn from enrichment data. One clear CTA."
        )
    )
    email_2: Email = Field(
        description=(
            "Follow-up sent 3–4 days after email 1. Different angle — "
            "a relevant case study, industry insight, or a pointed question. "
            "Acknowledge no response without being pushy. 4–6 sentences."
        )
    )
    email_3: Email = Field(
        description=(
            "Short breakup email. 2–3 sentences. "
            "Light touch, no guilt. Leave the door open. "
            "Make it clear this is the last outreach for now."
        )
    )
    sequence_notes: str = Field(
        description=(
            "Brief internal note explaining the personalisation strategy used: "
            "what specific signals from enrichment or qualification were leveraged, "
            "and why this angle was chosen for this prospect."
        )
    )


def sanitize_email_sequence(seq: EmailSequence, variables: Dict[str, str]) -> EmailSequence:
    return seq.model_copy(
        update={
            "email_1": Email(
                subject=sanitize_email_text(seq.email_1.subject, variables),
                body=sanitize_email_text(seq.email_1.body, variables),
            ),
            "email_2": Email(
                subject=sanitize_email_text(seq.email_2.subject, variables),
                body=sanitize_email_text(seq.email_2.body, variables),
            ),
            "email_3": Email(
                subject=sanitize_email_text(seq.email_3.subject, variables),
                body=sanitize_email_text(seq.email_3.body, variables),
            ),
            "sequence_notes": sanitize_email_text(seq.sequence_notes, variables),
        }
    )


class EmailCopywritingOutput(BaseModel):
    sequences: List[EmailSequence] = Field(
        description="One EmailSequence per approved lead, in input order."
    )
    batch_notes: str = Field(
        description=(
            "Brief copywriter's note on the batch: common themes across sequences, "
            "any leads where personalisation was limited due to sparse enrichment data, "
            "and suggested A/B test angles if applicable."
        )
    )


# Build copywriting prompt

def _build_copywriting_prompt(
    approved_leads: List[LeadResult],
    enrichments: List[LeadEnrichmentResult],
    decisions: List[LeadDecision],
    onboarding: OnboardingAgentOutput,
    rag_context: Optional[str] = None,
    sender_first_name: Optional[str] = None,
) -> str:
    brief = onboarding.product_brief

    if sender_first_name:
        sender_lines = [
            "== SENDER (sign-off) ==",
            f"Sign off each email using this sender first name exactly: {sender_first_name}",
            "(Use only plain text — no {{{{double-brace}}}} placeholders.)\n",
        ]
    else:
        sender_lines = [
            "== SENDER (sign-off) ==",
            "No sender first name is on file — sign off neutrally (e.g. 'Thanks,' or 'Best,') without a personal name.",
            "Do not use {{{{...}}}} placeholders or bracket tokens for the sender or anything else.\n",
        ]

    parts = [
        "You are a B2B email copywriter. Write a 3-email outreach sequence for each prospect.\n",
        "Use the product brief, ICP, enrichment data, and qualification pitch angle to personalise each sequence.\n",
        "Write final copy only: never output template tokens such as {{{{sender_name}}}}, {{{{name}}}}, {{{{company}}}}, or any {{{{...}}}} syntax.\n",
        "Use the prospect's real company and role from the data below; write names and companies as plain text.\n\n",
        *sender_lines,

        "== PRODUCT CONTEXT ==",
        f"Product: {brief.product_name}",
        f"What it does: {brief.what_it_does}",
        f"Who it's for: {brief.who_it_is_for}",
        f"Pain it solves: {brief.pain_it_solves}",
        f"Key differentiators: {', '.join(brief.key_differentiators)}",
        f"Ideal customer: {brief.ideal_customer_description}\n",

        "== EMAIL SEQUENCE RULES ==",
        "Email 1 — Cold outreach:",
        "  - 3–5 sentences MAX. Short is better.",
        "  - Open with ONE specific observation about the prospect or their company.",
        "    This must come from enrichment data (title, company, achievement, or company signal).",
        "    Do NOT open with 'I hope this email finds you well' or any generic opener.",
        "  - Connect that observation to the pain the product solves.",
        "  - One soft CTA: a question or a request for 15 minutes, not a hard sell.",
        "  - Sign off using the sender guidance above (real first name or neutral closing).\n",

        "Email 2 — Follow-up (send day 4):",
        "  - 4–6 sentences.",
        "  - Acknowledge no response briefly and move on — no guilt-tripping.",
        "  - Use a different angle: a relevant industry insight, a pointed question,",
        "    or a short case study reference (you can invent a plausible anonymised one).",
        "  - Reinforce one key differentiator.",
        "  - Same soft CTA or slightly more direct.\n",

        "Email 3 — Breakup email (send day 10):",
        "  - 2–3 sentences MAX.",
        "  - Friendly, no pressure, no guilt.",
        "  - Make clear this is the last email for now.",
        "  - Leave the door open for the future.\n",

        "TONE: Conversational, direct, human. No buzzwords. No 'synergies', 'leverage', 'circle back'.",
        "FORMAT: Plain text only. No bullet points, no HTML, no markdown in the email body.",
        "Never use {{{{double-brace}}}} placeholders — only literal words.\n",
    ]

    if rag_context:
        parts += [
            "",
            "== KNOWLEDGE BASE (templates, policies, FAQs, positioning — stay consistent; do not invent facts beyond this + product context) ==",
            rag_context,
            "",
        ]

    parts += [
        "== PROSPECTS ==",
    ]

    for i, (lead, enrichment, decision) in enumerate(
        zip(approved_leads, enrichments, decisions), 1
    ):
        parts.append(f"\n--- Prospect {i}: {lead.name} ---")
        parts.append(f"Email address: {lead.email}")
        parts.append(f"lead_index: {decision.lead_index}")

        # Role context
        verified_title = enrichment.enriched_data.current_title or lead.title
        parts.append(f"Verified title: {verified_title}")
        parts.append(f"Company: {lead.company}")
        if lead.industry:
            parts.append(f"Industry: {lead.industry}")
        if lead.location:
            parts.append(f"Location: {lead.location}, {lead.country or ''}")
        if lead.company_size:
            parts.append(f"Company size: {lead.company_size} employees")

        # Enrichment signals
        if enrichment.enriched_data.notable_achievements:
            parts.append(f"Notable achievements: {'; '.join(enrichment.enriched_data.notable_achievements)}")
        if enrichment.enriched_data.company_signals:
            signals = ", ".join(
                f"{s.key}: {s.value}" for s in enrichment.enriched_data.company_signals
            )
            parts.append(f"Company signals: {signals}")
        if enrichment.discrepancies:
            for d in enrichment.discrepancies:
                parts.append(
                    f"Note: company name discrepancy — provider says '{d.original_value}', "
                    f"search found '{d.found_value}'. Use the verified name in emails."
                )

        # Qualification context
        parts.append(f"ICP fit score: {decision.icp_match_score:.0%}")
        if decision.recommended_angle:
            parts.append(f"Recommended pitch angle: {decision.recommended_angle}")
        if decision.review_flags:
            parts.append(f"Copywriter caution: {'; '.join(decision.review_flags)}")

        parts.append("")

    return "\n".join(parts)


async def _run_email_copywriting_batch(
    approved_leads: List[LeadResult],
    enrichments: List[LeadEnrichmentResult],
    decisions: List[LeadDecision],
    onboarding: OnboardingAgentOutput,
    rag_context: Optional[str],
    sender_first: Optional[str],
) -> EmailCopywritingOutput:
    model = LitellmModel(model="openai/gpt-4.1-nano")

    with trace("email_copywriting_agent"):
        agent = Agent(
            name="EmailCopywritingAgent",
            instructions=COPYWRITING_INSTRUCTIONS,
            model=model,
            output_type=EmailCopywritingOutput,
        )

        prompt = _build_copywriting_prompt(
            approved_leads,
            enrichments,
            decisions,
            onboarding,
            rag_context=rag_context,
            sender_first_name=sender_first,
        )

        logger.info(f"[EmailAgent] Writing sequences for {len(approved_leads)} prospect(s) in batch.")
        try:
            result = await Runner.run(agent, prompt, max_turns=5)
        except MaxTurnsExceeded:
            logger.error("[EmailAgent] Max turns exceeded.")
            raise

    if isinstance(result.final_output, str):
        output = EmailCopywritingOutput.model_validate_json(result.final_output)
    else:
        output = EmailCopywritingOutput.model_validate(result.final_output)

    if len(output.sequences) != len(approved_leads):
        logger.warning(
            f"[EmailAgent] Batch expected {len(approved_leads)} sequences, got {len(output.sequences)}."
        )

    return output


@agent_observe("email_copywriting_agent", as_type="agent")
async def run_email_copywriting_agent(
    approved_leads: List[LeadResult],
    enrichment_output_map: dict,  # lead_index → LeadEnrichmentResult
    decisions: List[LeadDecision],
    onboarding: OnboardingAgentOutput,
    user_id: Optional[str] = None,
    sender_display_name: Optional[str] = None,
) -> EmailCopywritingOutput:
    """
    approved_leads: LeadResult list for approved+review leads only
    enrichment_output_map: dict mapping lead_index (1-based) to LeadEnrichmentResult
    decisions: LeadDecision list (approved + review decisions, same order as approved_leads)
    onboarding: OnboardingAgentOutput from the client onboarding step
    """
    if not approved_leads:
        logger.warning("[EmailAgent] No approved leads to write sequences for.")
        return EmailCopywritingOutput(sequences=[], batch_notes="No approved leads provided.")

    enrichments = [enrichment_output_map[d.lead_index] for d in decisions]

    sender_first = _first_token(sender_display_name)

    rag_context: Optional[str] = None
    if user_id:
        try:
            rag_context = retrieve_sequence_rag_context(user_id, onboarding)
        except Exception as e:
            logger.warning("[EmailAgent] RAG retrieval for sequences failed: %s", e)

    n = len(approved_leads)
    slices = chunk_indices(n)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def run_slice(
        start: int, end: int
    ) -> Tuple[int, int, Optional[EmailCopywritingOutput]]:
        alb = approved_leads[start:end]
        enb = enrichments[start:end]
        dcb = decisions[start:end]
        async with sem:
            try:
                out = await async_run_with_retries(
                    lambda: _run_email_copywriting_batch(
                        alb, enb, dcb, onboarding, rag_context, sender_first
                    )
                )
                return (start, end, out)
            except Exception as e:
                logger.error(
                    f"[EmailAgent] Batch [{start}:{end}] failed after retries: {e}"
                )
                return (start, end, None)

    tasks = [asyncio.create_task(run_slice(s, e)) for s, e in slices]
    resolved = await asyncio.gather(*tasks)
    resolved.sort(key=lambda x: x[0])

    merged_sequences: List[EmailSequence] = []
    notes_parts: List[str] = []
    sanitized: List[EmailSequence] = []

    for start, end, part in resolved:
        if part is None:
            continue
        alb = approved_leads[start:end]
        dcb = decisions[start:end]
        if part.batch_notes:
            notes_parts.append(part.batch_notes)

        if len(part.sequences) != len(alb):
            logger.warning(
                f"[EmailAgent] Batch [{start}:{end}] returned {len(part.sequences)} sequences "
                f"for {len(alb)} prospects."
            )

        for seq, lead, decision in zip(part.sequences, alb, dcb):
            enr = enrichment_output_map.get(decision.lead_index)
            verified_title = None
            if enr and enr.enriched_data:
                verified_title = enr.enriched_data.current_title
            if not verified_title:
                verified_title = lead.title
            vars_map = build_substitution_vars(
                lead=lead,
                onboarding=onboarding,
                sender_display_name=sender_display_name,
                verified_title=verified_title,
            )
            sanitized.append(sanitize_email_sequence(seq, vars_map))

    batch_notes = "\n---\n".join(notes_parts) if notes_parts else ""

    if len(sanitized) != len(approved_leads):
        logger.warning(
            f"[EmailAgent] Expected {len(approved_leads)} sequences after merge, "
            f"got {len(sanitized)} (missing batches omitted)."
        )

    output = EmailCopywritingOutput(sequences=sanitized, batch_notes=batch_notes)

    for seq in output.sequences:
        for email_step, email in [("email_1", seq.email_1), ("email_2", seq.email_2), ("email_3", seq.email_3)]:
            if "<" in email.body and ">" in email.body:
                logger.warning(
                    f"[EmailAgent] {seq.lead_name} {email_step} may contain HTML — review before sending."
                )

    logger.info(f"[EmailAgent] Done. {len(output.sequences)} sequence(s) written.")
    return output