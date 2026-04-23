"""
reply_agent.py
--------------
AI-powered reply classification and response agent.

Agent pattern:
  - Follows your established pattern: Agent + Runner + LiteLLM + Pydantic I/O
  - Input:  ReplyAgentInput  (Pydantic)
  - Output: ReplyAgentOutput (Pydantic, structured)

Classifications:
  interested       → lead wants to proceed; draft RAG reply + embed Cal.com link
  not_interested   → polite no; thank them, close the thread, mark Inactive
  oof              → out of office; pause 7 days, continue from where sequence left off
  opt_out          → unsubscribe intent; mark Do Not Contact, cancel all follow-ups
  wrong_person     → referred to someone else; extract referral, create new lead
  ambiguous        → unclear; flag for human review

RAG usage:
  Only triggered for 'interested' classification.
  Agent queries the RAG store to find relevant context (FAQ, company info,
  email templates) before drafting the response.

The agent NEVER sends the response itself.
It returns the drafted response and the action to take.
The caller (webhook handler) executes the action.
"""

import asyncio
import logging
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from agents import Agent, Runner, trace, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel

from backend.core.observability import agent_observe
from backend.core.outreach.agents.instruction import REPLY_AGENT_INSTRUCTIONS

logger = logging.getLogger(__name__)



# INPUT MODEL

class ReplyAgentInput(BaseModel):
    """
    All context the reply agent needs to classify a reply and decide what to do.
    """

    # Lead context
    lead_id: str = Field(..., description="Database ID of the lead who replied.")
    lead_name: Optional[str] = Field(None, description="Full name of the lead.")
    lead_email: str = Field(..., description="Email address the reply came from.")
    lead_company: Optional[str] = Field(None, description="Company the lead works at.")
    lead_title: Optional[str] = Field(None, description="Job title of the lead.")

    # Reply content
    reply_subject: Optional[str] = Field(None, description="Subject line of the inbound reply.")
    reply_body_text: str = Field(..., description="Plain text body of the inbound reply.")
    reply_body_html: Optional[str] = Field(None, description="HTML body of the inbound reply.")

    # Original email context
    original_email_number: int = Field(
        ..., ge=1, le=3,
        description="Which email in the sequence (1, 2, or 3) the lead is replying to."
    )
    original_subject: Optional[str] = Field(
        None, description="Subject of the original outreach email sent."
    )

    # Product context
    product_name: str = Field(..., description="Name of the product being sold.")
    product_pain: str = Field(..., description="Pain point the product solves.")
    product_differentiators: List[str] = Field(
        default_factory=list,
        description="Key differentiators of the product for use in replies."
    )

    # RAG context (retrieved before calling agent)
    rag_context: Optional[str] = Field(
        None,
        description=(
            "Relevant context retrieved from the RAG store (FAQ, company info, templates). "
            "Pre-fetched by the caller before invoking the agent. "
            "Empty if classification is not 'interested'."
        )
    )

    # Sender info
    sender_name: str = Field(..., description="Name of the human sender (the platform user).")
    cal_link: Optional[str] = Field(
        None, description="Cal.com booking link to embed when lead shows interest."
    )

    # Extended context (assembled by reply_handler from DB + logs)
    icp_context: Optional[str] = Field(
        None,
        description="Formatted ideal customer profile for the campaign.",
    )
    lead_details_text: Optional[str] = Field(
        None,
        description="Additional lead fields from the database (status, location, LinkedIn, etc.).",
    )
    product_brief_extended: Optional[str] = Field(
        None,
        description=(
            "Full product brief text (what_it_does, who_it_is_for, ideal_customer, etc.). "
            "When set, prefer this over the compact product fields."
        ),
    )
    conversation_history: Optional[str] = Field(
        None,
        description=(
            "Chronological outbound/inbound thread for this lead before the current reply "
            "(from outreach_log + reply_log)."
        ),
    )


# OUTPUT MODEL

class ReferralExtraction(BaseModel):
    """Extracted referral details when lead says 'talk to Bob'."""

    name: Optional[str] = Field(
        None, description="Name of the referred person, if mentioned."
    )
    email: Optional[str] = Field(
        None, description="Email address of the referred person, extracted from reply."
    )
    context: Optional[str] = Field(
        None,
        description="Any additional context about the referred person extracted from the reply."
    )


class ReplyAgentOutput(BaseModel):
    """
    Structured output from the reply agent.
    The caller executes the recommended action — the agent never sends directly.
    """

    classification: Literal[
        "interested",
        "not_interested",
        "oof",
        "opt_out",
        "wrong_person",
        "ambiguous",
    ] = Field(
        ...,
        description=(
            "Intent classification of the inbound reply. "
            "'interested' = genuine interest, proceed with reply + booking link. "
            "'not_interested' = polite decline, close thread. "
            "'oof' = automated out-of-office, pause and retry later. "
            "'opt_out' = unsubscribe request, mark Do Not Contact. "
            "'wrong_person' = referred to someone else, extract referral. "
            "'ambiguous' = unclear intent, flag for human review."
        )
    )

    confidence_score: float = Field(
        ..., ge=0.0, le=1.0,
        description=(
            "Confidence in the classification. "
            "1.0 = certain. 0.5 = ambiguous. Below 0.6 → default to 'ambiguous'."
        )
    )

    classification_reason: str = Field(
        ...,
        description="One sentence explaining why this classification was chosen."
    )

    # Action to take
    recommended_action: Literal[
        "reply_with_rag",     # send drafted response, embed Cal.com link
        "close_thread",       # send polite close, mark Inactive
        "pause_lead",         # pause follow-ups 7 days (OOO)
        "do_not_contact",     # mark Do Not Contact, cancel all follow-ups
        "create_referral",    # create new lead from referral, skip to outreach
        "flag_review",        # flag for human review, no automated action
    ] = Field(
        ...,
        description="The action the system should take based on classification."
    )

    # Drafted response (populated for interested, not_interested)
    drafted_response_subject: Optional[str] = Field(
        None,
        description=(
            "Subject line for the drafted response. "
            "Use 'Re: {original_subject}' format. "
            "Only populated for 'interested' and 'not_interested' classifications."
        )
    )

    drafted_response_body: Optional[str] = Field(
        None,
        description=(
            "Full plain-text body of the drafted response. "
            "For 'interested': answer their question using RAG context, embed Cal.com link. "
            "For 'not_interested': short, warm close — thank them, leave door open. "
            "Never use HTML. Use {{sender_name}} placeholder for sender's name. "
            "Embed Cal.com link naturally in the flow for 'interested' replies."
        )
    )

    # Referral details (populated for wrong_person)
    referral: Optional[ReferralExtraction] = Field(
        None,
        description="Extracted referral details. Only populated for 'wrong_person' classification."
    )

    # OOF resume date
    resume_after_days: Optional[int] = Field(
        None,
        description=(
            "For 'oof' classification: number of days to pause before resuming. "
            "Default 7. Extract from OOF message if a specific return date is mentioned."
        )
    )

    # Internal notes
    agent_notes: str = Field(
        ...,
        description=(
            "Internal reasoning notes: what signals in the reply led to this classification, "
            "what RAG context was used (if any), and any caveats."
        )
    )


# PROMPT BUILDER

def _build_reply_prompt(inp: ReplyAgentInput) -> str:
    parts = [
        "Classify this inbound reply and recommend the appropriate action.\n",
        "== LEAD ==",
        f"Name: {inp.lead_name or 'Unknown'}",
        f"Email: {inp.lead_email}",
        f"Company: {inp.lead_company or 'Unknown'}",
        f"Title: {inp.lead_title or 'Unknown'}",
    ]

    if inp.lead_details_text:
        parts += ["", "== LEAD RECORD (database) ==", inp.lead_details_text]

    if inp.icp_context:
        parts += ["", "== IDEAL CUSTOMER PROFILE (ICP) ==", inp.icp_context]

    if inp.product_brief_extended:
        parts += ["", "== PRODUCT BRIEF (full) ==", inp.product_brief_extended]
    else:
        parts += [
            "",
            "== PRODUCT BRIEF ==",
            f"Product: {inp.product_name}",
            f"Pain it solves: {inp.product_pain}",
            f"Differentiators: {', '.join(inp.product_differentiators)}",
        ]

    if inp.conversation_history:
        parts += ["", "== EMAIL THREAD SO FAR (prior messages) ==", inp.conversation_history]

    parts += [
        "",
        "== CURRENT INBOUND REPLY (classify this message) ==",
        f"Subject: {inp.reply_subject or '(no subject)'}",
        f"Body:\n{inp.reply_body_text}",
        "",
        f"== CONTEXT: This is a reply to sequence email {inp.original_email_number} ==",
        f"Original outbound subject (that email): {inp.original_subject or 'cold outreach'}",
    ]

    if inp.rag_context:
        parts += [
            "",
            "== RAG CONTEXT (use this to answer questions) ==",
            inp.rag_context,
        ]

    if inp.cal_link:
        parts += [
            "",
            f"== CAL.COM BOOKING LINK ==",
            inp.cal_link,
            "(embed this naturally in your response for 'interested' leads)",
        ]

    parts += [
        "",
        f"Sender name placeholder: {{{{sender_name}}}}",
        f"Sender's name: {inp.sender_name}",
    ]

    return "\n".join(parts)


# AGENT RUNNER


@agent_observe("reply_agent", as_type="agent")
async def run_reply_agent(inp: ReplyAgentInput) -> ReplyAgentOutput:
    """
    Run the reply classification and response drafting agent.

    Args:
        inp: ReplyAgentInput — full context about the inbound reply

    Returns:
        ReplyAgentOutput — classification, recommended action, drafted response if applicable

    Raises:
        ValueError: If agent output fails Pydantic validation
    """
    model = LitellmModel(model="openai/gpt-4.1-nano")

    with trace("reply_agent"):
        agent = Agent(
            name="ReplyAgent",
            instructions=REPLY_AGENT_INSTRUCTIONS,
            model=model,
            output_type=ReplyAgentOutput,
        )

        prompt = _build_reply_prompt(inp)
        logger.info(
            f"[ReplyAgent] Classifying reply from {inp.lead_email} "
            f"(Email {inp.original_email_number} reply)"
        )

        try:
            result = await Runner.run(agent, prompt, max_turns=3)
        except MaxTurnsExceeded:
            logger.error("[ReplyAgent] Max turns exceeded — defaulting to ambiguous")
            return ReplyAgentOutput(
                classification="ambiguous",
                confidence_score=0.0,
                classification_reason="Agent exceeded max turns — could not classify.",
                recommended_action="flag_review",
                agent_notes="MaxTurnsExceeded — manual review required.",
            )

        try:
            if isinstance(result.final_output, str):
                output = ReplyAgentOutput.model_validate_json(result.final_output)
            else:
                output = ReplyAgentOutput.model_validate(result.final_output)
        except Exception as e:
            logger.error(f"[ReplyAgent] Pydantic validation failed: {e}")
            raise ValueError(f"Reply agent output validation failed: {e}")

        # Post-validation: enforce confidence threshold
        if output.confidence_score < 0.6 and output.classification != "ambiguous":
            logger.warning(
                f"[ReplyAgent] Low confidence ({output.confidence_score:.0%}) "
                f"for '{output.classification}' — overriding to ambiguous"
            )
            output.classification = "ambiguous"
            output.recommended_action = "flag_review"
            output.drafted_response_subject = None
            output.drafted_response_body = None

        logger.info(
            f"[ReplyAgent] Result: {output.classification} "
            f"(confidence={output.confidence_score:.0%}) "
            f"→ action={output.recommended_action}"
        )

        return output
