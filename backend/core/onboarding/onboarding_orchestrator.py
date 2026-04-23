"""
Orchestrator onboarding: combines Playwright subagent, Fetch MCP subagent, and Serper search.

Does not replace `run_onboarding_agent` unless callers switch explicitly.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List

import httpx
from agents import Agent, Runner, MaxTurnsExceeded, function_tool, trace
from agents.extensions.models.litellm_model import LitellmModel

from backend.core.observability import agent_observe
from backend.core.onboarding.instruction import ONBOARDING_ORCHESTRATOR_INSTRUCTIONS
from backend.core.onboarding.onboarding_models import (
    ICPOutput,
    OnboardingAgentInput,
    OnboardingAgentOutput,
    ProductBriefOutput,
)
from backend.core.onboarding.onboarding_subagents import (
    format_subagent_snapshot,
    run_fetch_onboarding_inner,
    run_playwright_onboarding_inner,
)

logger = logging.getLogger(__name__)

SERPER_BASE_URL = os.getenv("SERPER_BASE_URL", "https://google.serper.dev/search")
ORCHESTRATOR_MODEL = "openai/gpt-4.1-nano"


@dataclass
class OrchestratorToolBudget:
    max_per_tool: int
    playwright_calls: int = 0
    fetch_calls: int = 0
    serper_calls: int = 0


def _format_serper_results(raw_results: Any) -> str:
    """Compact digest for the orchestrator LLM."""
    if not isinstance(raw_results, list):
        return json.dumps({"error": "unexpected Serper response shape", "raw_type": type(raw_results).__name__})

    lines: List[str] = []
    for i, block in enumerate(raw_results):
        if not isinstance(block, dict):
            continue
        q = block.get("searchParameters", {}).get("q", f"query_{i}")
        lines.append(f"### Query: {q}")
        organic = block.get("organic") or []
        for j, row in enumerate(organic[:6]):
            title = row.get("title") or ""
            link = row.get("link") or ""
            snip = (row.get("snippet") or "")[:400]
            lines.append(f"  - {title} | {link}\n    {snip}")
        kg = block.get("knowledgeGraph")
        if isinstance(kg, dict) and kg.get("title"):
            lines.append(f"  [KG] {kg.get('title')} — {kg.get('description', '')[:300]}")
        lines.append("")
    return "\n".join(lines) if lines else "(no organic results)"


async def _serper_search_once(queries: List[str]) -> str:
    key = (os.getenv("SERPER_API_KEY") or "").strip()
    if not key:
        return json.dumps({"error": "SERPER_API_KEY not set", "hint": "Set env to enable Serper in orchestrator."})

    payload = [{"q": q} for q in queries]
    headers = {
        "X-API-KEY": key,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            SERPER_BASE_URL,
            headers=headers,
            json=payload,
            timeout=45.0,
        )
        response.raise_for_status()
        raw_results = response.json()

    digest = _format_serper_results(raw_results)
    return f"Serper results ({len(queries)} queries):\n{digest}"


@agent_observe("onboarding_orchestrator", as_type="agent")
async def run_onboarding_orchestrator(
    user_input: OnboardingAgentInput,
    *,
    max_turns: int = 28,
    max_calls_per_tool: int = 2,
    raise_on_low_confidence: bool = True,
    low_confidence_threshold: float = 0.2,
) -> OnboardingAgentOutput:
    """
    Run the orchestrator agent with three tools (Playwright, Fetch MCP, Serper).
    Each tool may be invoked at most `max_calls_per_tool` times per run.
    """
    budget = OrchestratorToolBudget(max_per_tool=max_calls_per_tool)
    model = LitellmModel(model=ORCHESTRATOR_MODEL)

    ui = user_input

    def _fail_all(msg: str) -> OnboardingAgentOutput:
        return OnboardingAgentOutput(
            icp=ICPOutput(target_type="both", industry=[], job_titles=[], locations=[]),
            product_brief=ProductBriefOutput(
                product_name="Unknown",
                what_it_does="N/A",
                who_it_is_for="N/A",
                pain_it_solves="N/A",
                key_differentiators=[],
                ideal_customer_description="N/A",
            ),
            confidence_score=0.0,
            missing_fields=["ALL — " + msg],
        )

    @function_tool
    async def research_with_playwright() -> str:
        """Run the Playwright (headless browser) onboarding researcher on the campaign homepage."""
        if budget.playwright_calls >= budget.max_per_tool:
            return json.dumps(
                {
                    "error": "Budget exhausted for research_with_playwright",
                    "max_per_tool": budget.max_per_tool,
                }
            )
        budget.playwright_calls += 1
        try:
            out = await run_playwright_onboarding_inner(ui)
            return format_subagent_snapshot("playwright", out)
        except Exception as e:
            logger.exception("[Orchestrator] playwright tool failed")
            return json.dumps({"error": str(e), "source": "playwright"})

    @function_tool
    async def research_with_fetch_mcp() -> str:
        """Run the HTTP Fetch MCP onboarding researcher on the homepage (no browser)."""
        if budget.fetch_calls >= budget.max_per_tool:
            return json.dumps(
                {
                    "error": "Budget exhausted for research_with_fetch_mcp",
                    "max_per_tool": budget.max_per_tool,
                }
            )
        budget.fetch_calls += 1
        try:
            out = await run_fetch_onboarding_inner(ui)
            return format_subagent_snapshot("fetch_mcp", out)
        except Exception as e:
            logger.exception("[Orchestrator] fetch tool failed")
            return json.dumps({"error": str(e), "source": "fetch_mcp"})

    @function_tool
    async def search_company_with_serper(queries: List[str]) -> str:
        """
        Search Google via Serper for external context (news, about, social). Pass 2–8 short queries in one call.
        """
        if budget.serper_calls >= budget.max_per_tool:
            return json.dumps(
                {
                    "error": "Budget exhausted for search_company_with_serper",
                    "max_per_tool": budget.max_per_tool,
                }
            )
        budget.serper_calls += 1
        clean = [x.strip() for x in queries if x and x.strip()][:10]
        if not clean:
            return json.dumps({"error": "No queries provided"})
        try:
            return await _serper_search_once(clean)
        except Exception as e:
            logger.exception("[Orchestrator] Serper tool failed")
            return json.dumps({"error": str(e), "source": "serper"})

    agent = Agent(
        name="OnboardingOrchestrator",
        instructions=ONBOARDING_ORCHESTRATOR_INSTRUCTIONS,
        model=model,
        tools=[research_with_playwright, research_with_fetch_mcp, search_company_with_serper],
        output_type=OnboardingAgentOutput,
    )

    prompt_parts = [
        "Produce the final onboarding profile.",
        f"Website URL: {ui.website_url}",
    ]
    if ui.company_name:
        prompt_parts.append(f"Company name (hint): {ui.company_name}")
    prompt = "\n".join(prompt_parts)

    with trace("onboarding orchestrator"):
        try:
            logger.info(f"[Orchestrator] Starting for {ui.website_url}")
            result = await Runner.run(agent, prompt, max_turns=max_turns)
            logger.info(f"[Orchestrator] Runner finished for {ui.website_url}")
        except MaxTurnsExceeded:
            logger.error(f"[Orchestrator] MaxTurnsExceeded for {ui.website_url}")
            return _fail_all("orchestrator exceeded max turns")

    try:
        if isinstance(result.final_output, str):
            output_data = OnboardingAgentOutput.model_validate_json(result.final_output)
        else:
            output_data = OnboardingAgentOutput.model_validate(result.final_output)
    except Exception as e:
        logger.error(f"[Orchestrator] Validation failed: {e}")
        raise ValueError(f"Failed to validate orchestrator output: {e}") from e

    if raise_on_low_confidence and output_data.confidence_score <= low_confidence_threshold:
        logger.error(
            f"[Orchestrator] Low confidence ({output_data.confidence_score}) below {low_confidence_threshold}"
        )
        raise ValueError(
            f"Result does not pass: Confidence score is too low ({output_data.confidence_score * 100}%). "
            f"Missing fields: {output_data.missing_fields}"
        )

    return output_data
