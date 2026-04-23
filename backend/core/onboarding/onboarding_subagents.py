"""
Playwright- and Fetch-MCP–based onboarding researchers (no confidence gate).
Used by `run_onboarding_agent` and the orchestrator.
"""

import json
import logging

from agents import Agent, Runner, MaxTurnsExceeded, trace
from agents.extensions.models.litellm_model import LitellmModel
from agents.mcp import MCPServerStdio

from backend.core.observability import agent_observe
from backend.core.onboarding.instruction import (
    ONBOARDING_INSTRUCTIONS,
    ONBOARDING_INSTRUCTIONS_FETCH,
)
from backend.core.onboarding.onboarding_models import (
    ICPOutput,
    OnboardingAgentInput,
    OnboardingAgentOutput,
    ProductBriefOutput,
)

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-4.1-nano"

playwright_args = [
    "@playwright/mcp@latest",
    "--headless",
    "--isolated",
    "--no-sandbox",
    "--ignore-https-errors",
    "--user-agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
]
playwright_params = {"command": "npx", "args": playwright_args}
fetch_params = {"command": "uvx", "args": ["mcp-server-fetch"]}

_FAIL_OUTPUT = OnboardingAgentOutput(
    icp=ICPOutput(
        target_type="both",
        industry=[],
        job_titles=[],
        locations=[],
    ),
    product_brief=ProductBriefOutput(
        product_name="Unknown",
        what_it_does="N/A",
        who_it_is_for="N/A",
        pain_it_solves="N/A",
        key_differentiators=[],
        ideal_customer_description="N/A",
    ),
    confidence_score=0.0,
    missing_fields=["ALL - researcher failed or timed out"],
)


def _validate_output(result) -> OnboardingAgentOutput:
    if isinstance(result.final_output, str):
        return OnboardingAgentOutput.model_validate_json(result.final_output)
    return OnboardingAgentOutput.model_validate(result.final_output)


@agent_observe("onboarding_playwright_subagent", as_type="agent")
async def run_playwright_onboarding_inner(user_input: OnboardingAgentInput) -> OnboardingAgentOutput:
    """Playwright MCP agent; returns output without applying the API confidence gate."""
    model = LitellmModel(model=MODEL)
    prompt = f"Analyze the following website and create a profile: {user_input.website_url}"
    if user_input.company_name:
        prompt += f" (Company Name: {user_input.company_name})"

    with trace("onboarding playwright subagent"):
        async with MCPServerStdio(params=playwright_params, client_session_timeout_seconds=60) as mcp_server_browser:
            allowed_names = {"browser_navigate", "browser_evaluate"}
            original_list_tools = mcp_server_browser.list_tools

            async def filtered_list_tools(*args, **kwargs):
                all_tools = await original_list_tools(*args, **kwargs)
                return [t for t in all_tools if t.name in allowed_names]

            mcp_server_browser.list_tools = filtered_list_tools

            agent = Agent(
                name="OnboardingInvestigatorPlaywright",
                instructions=ONBOARDING_INSTRUCTIONS,
                model=model,
                mcp_servers=[mcp_server_browser],
                output_type=OnboardingAgentOutput,
            )

            try:
                logger.info(f"[PlaywrightSubagent] Running for {user_input.website_url}")
                result = await Runner.run(agent, prompt, max_turns=15)
                logger.info(f"[PlaywrightSubagent] Completed for {user_input.website_url}")
            except MaxTurnsExceeded:
                logger.error(f"[PlaywrightSubagent] MaxTurnsExceeded for {user_input.website_url}")
                out = _FAIL_OUTPUT.model_copy(
                    update={
                        "missing_fields": ["ALL - Agent timed out due to looping or errors"],
                    }
                )
                return out

            try:
                return _validate_output(result)
            except Exception as e:
                logger.error(f"[PlaywrightSubagent] Validation error: {e}")
                raise ValueError(f"Failed to validate Playwright subagent output: {e}") from e


@agent_observe("onboarding_fetch_subagent", as_type="agent")
async def run_fetch_onboarding_inner(user_input: OnboardingAgentInput) -> OnboardingAgentOutput:
    """Fetch MCP agent (mcp-server-fetch); same task as Playwright with different modality."""
    model = LitellmModel(model=MODEL)
    prompt = f"Analyze the following website and create a profile: {user_input.website_url}"
    if user_input.company_name:
        prompt += f" (Company Name: {user_input.company_name})"

    with trace("onboarding fetch subagent"):
        async with MCPServerStdio(params=fetch_params, client_session_timeout_seconds=60) as fetch_server:
            allowed_names = {"fetch"}
            original_list_tools = fetch_server.list_tools

            async def filtered_fetch_tools(*args, **kwargs):
                all_tools = await original_list_tools(*args, **kwargs)
                return [t for t in all_tools if t.name in allowed_names]

            fetch_server.list_tools = filtered_fetch_tools

            agent = Agent(
                name="OnboardingInvestigatorFetch",
                instructions=ONBOARDING_INSTRUCTIONS_FETCH,
                model=model,
                mcp_servers=[fetch_server],
                output_type=OnboardingAgentOutput,
            )

            try:
                logger.info(f"[FetchSubagent] Running for {user_input.website_url}")
                result = await Runner.run(agent, prompt, max_turns=12)
                logger.info(f"[FetchSubagent] Completed for {user_input.website_url}")
            except MaxTurnsExceeded:
                logger.error(f"[FetchSubagent] MaxTurnsExceeded for {user_input.website_url}")
                return _FAIL_OUTPUT.model_copy(
                    update={
                        "missing_fields": ["ALL - Fetch agent timed out"],
                    }
                )

            try:
                return _validate_output(result)
            except Exception as e:
                logger.error(f"[FetchSubagent] Validation error: {e}")
                raise ValueError(f"Failed to validate Fetch subagent output: {e}") from e


def format_subagent_snapshot(label: str, out: OnboardingAgentOutput) -> str:
    """Compact JSON for orchestrator context."""
    payload = {
        "source": label,
        "confidence_score": out.confidence_score,
        "missing_fields": out.missing_fields,
        "icp": out.icp.model_dump(),
        "product_brief": out.product_brief.model_dump(),
    }
    return json.dumps(payload, indent=2)
