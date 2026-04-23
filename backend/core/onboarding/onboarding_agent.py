"""
Onboarding agents: legacy Playwright-only entrypoint (`run_onboarding_agent`) and shared models.

Orchestrated multi-source onboarding lives in `onboarding_orchestrator.py`.
"""

import logging

from backend.core.observability import agent_observe
from backend.core.onboarding.onboarding_models import (
    ICPOutput,
    OnboardingAgentInput,
    OnboardingAgentOutput,
    ProductBriefOutput,
)
from backend.core.onboarding.onboarding_subagents import run_playwright_onboarding_inner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Re-export models for existing imports (`pipeline_runner`, `mock_data`, etc.)
__all__ = [
    "ICPOutput",
    "OnboardingAgentInput",
    "OnboardingAgentOutput",
    "ProductBriefOutput",
    "run_onboarding_agent",
]


@agent_observe("onboarding_agent", as_type="agent")
async def run_onboarding_agent(user_input: OnboardingAgentInput) -> OnboardingAgentOutput:
    """
    Original behaviour: Playwright MCP only, with confidence gate (≤0.2 fails).
    """
    output_data = await run_playwright_onboarding_inner(user_input)

    if output_data.confidence_score <= 0.2:
        logger.error(
            f"Result does not pass: Confidence score is too low ({output_data.confidence_score * 100}%). "
        )
        raise ValueError(
            f"Result does not pass: Confidence score is too low ({output_data.confidence_score * 100}%). "
            f"Missing fields: {output_data.missing_fields}"
        )

    return output_data
