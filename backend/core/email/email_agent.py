# email_agent.py

import asyncio
import logging
from typing import List
from pydantic import BaseModel, Field
from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from core.ingestion.lead_ingestion import LeadResult
from core.enrichment.enrichment_agent import LeadEnrichmentResult
from core.onboarding.onboarding_agent import OnboardingAgentOutput
from core.qualification.qualification_agent import LeadDecision

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
) -> str:
    brief = onboarding.product_brief
    icp = onboarding.icp

    parts = [
        "You are a B2B email copywriter. Write a 3-email outreach sequence for each prospect.\n",
        "Use the product brief, ICP, enrichment data, and qualification pitch angle to personalise each sequence.\n\n",

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
        "  - Sign off with the sender's first name only (use placeholder: {{sender_name}}).\n",

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
        "SENDER PLACEHOLDER: Use {{sender_name}} for the sender's name throughout.\n",

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


# Copywriting instructions

COPYWRITING_INSTRUCTIONS = """
You are a senior B2B email copywriter specialising in outbound sales sequences.
Your emails are known for being specific, human, and never sounding like templates.

CRITICAL RULES:
- Email 1 MUST open with a specific, verifiable observation about the prospect.
  Use their verified title, company name (use the verified name if discrepancy noted),
  a notable achievement, or a company signal from the enrichment data.
  If enrichment data is sparse, use their role + company context creatively.
- Never fabricate achievements or facts not present in the prospect data.
- Never use generic openers: no "I hope...", no "My name is...", no "I came across your profile".
- Email bodies must be plain text — no bullet points, no markdown, no HTML.
- Each email must feel like it was written specifically for this person, not merged from a template.
- Use {{sender_name}} as the sender placeholder throughout all emails.
- sequence_notes must explain which specific enrichment signals drove the personalisation choices.
- Return one EmailSequence per prospect, in input order.
"""


# Run email copywriting agent

async def run_email_copywriting_agent(
    approved_leads: List[LeadResult],
    enrichment_output_map: dict,  # lead_index → LeadEnrichmentResult
    decisions: List[LeadDecision],
    onboarding: OnboardingAgentOutput,
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

    # Match enrichments to leads via lead_index
    enrichments = [enrichment_output_map[d.lead_index] for d in decisions]

    model = LitellmModel(model="openai/gpt-4.1-nano")

    with trace("email_copywriting_agent"):
        agent = Agent(
            name="EmailCopywritingAgent",
            instructions=COPYWRITING_INSTRUCTIONS,
            model=model,
            output_type=EmailCopywritingOutput,
        )

        prompt = _build_copywriting_prompt(
            approved_leads, enrichments, decisions, onboarding
        )

        logger.info(
            f"[EmailAgent] Writing sequences for {len(approved_leads)} prospect(s)."
        )
        try:
            result = await Runner.run(agent, prompt, max_turns=5)
        except MaxTurnsExceeded:
            logger.error("[EmailAgent] Max turns exceeded.")
            raise

    if isinstance(result.final_output, str):
        output = EmailCopywritingOutput.model_validate_json(result.final_output)
    else:
        output = EmailCopywritingOutput.model_validate(result.final_output)

    # Post-validation
    if len(output.sequences) != len(approved_leads):
        raise ValueError(
            f"Expected {len(approved_leads)} sequences, got {len(output.sequences)}."
        )

    for seq in output.sequences:
        # Verify sender placeholder is present
        for email_step, email in [("email_1", seq.email_1), ("email_2", seq.email_2), ("email_3", seq.email_3)]:
            if "{{sender_name}}" not in email.body:
                logger.warning(
                    f"[EmailAgent] {seq.lead_name} {email_step} missing {{{{sender_name}}}} placeholder."
                )
        # Verify no HTML leaked in
        for email_step, email in [("email_1", seq.email_1), ("email_2", seq.email_2), ("email_3", seq.email_3)]:
            if "<" in email.body and ">" in email.body:
                logger.warning(
                    f"[EmailAgent] {seq.lead_name} {email_step} may contain HTML — review before sending."
                )

    logger.info(f"[EmailAgent] Done. {len(output.sequences)} sequence(s) written.")
    return output


# Test main

if __name__ == "__main__":
    from core.mock_data import (
        MOCK_ENRICHED_LEADS,
        MOCK_ENRICHMENT_OUTPUT,
        MOCK_QUALIFICATION_OUTPUT,
        MOCK_ONBOARDING_ANDELA,
    )

    async def main():
        # Collect approved + review decisions (both get emails)
        decisions_to_write = (
            MOCK_QUALIFICATION_OUTPUT.approved +
            MOCK_QUALIFICATION_OUTPUT.review
        )

        # Map lead_index → LeadEnrichmentResult for fast lookup
        enrichment_map = {
            e.lead_index: e
            for e in MOCK_ENRICHMENT_OUTPUT.enriched_leads
        }

        # Map lead_index → LeadResult for fast lookup
        lead_map = {i + 1: lead for i, lead in enumerate(MOCK_ENRICHED_LEADS)}
        approved_leads = [lead_map[d.lead_index] for d in decisions_to_write]

        print(f"Writing email sequences for {len(approved_leads)} prospect(s)...\n")

        try:
            output = await run_email_copywriting_agent(
                approved_leads=approved_leads,
                enrichment_output_map=enrichment_map,
                decisions=decisions_to_write,
                onboarding=MOCK_ONBOARDING_ANDELA,
            )

            print("\n" + "=" * 80)
            print("EMAIL SEQUENCES")
            print("=" * 80)

            for seq in output.sequences:
                print(f"\n{'─' * 60}")
                print(f"{seq.lead_name} <{seq.lead_email}>")
                print(f"{'─' * 60}")

                for step, email in [
                    ("EMAIL 1 — Cold outreach", seq.email_1),
                    ("EMAIL 2 — Follow-up (Day 4)", seq.email_2),
                    ("EMAIL 3 — Breakup (Day 10)", seq.email_3),
                ]:
                    print(f"\n {step}")
                    print(f"Subject: {email.subject}")
                    print(f"\n{email.body}")

                print(f"\n Sequence notes: {seq.sequence_notes}")

            print(f"\n{'─' * 60}")
            print(f" Batch notes: {output.batch_notes}")

        except Exception as e:
            print(f" Email writing failed: {e}")
            raise

    asyncio.run(main())