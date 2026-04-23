"""
Manual test: orchestrator + Playwright + Fetch MCP + Serper.

Run from sda_platform:
  uv run python -m backend.core.onboarding.onboarding_orchestrator_test

Requires: npx + Playwright MCP, uvx mcp-server-fetch, network, API keys as for other agents.
Set SERPER_API_KEY for Serper. To only test tools without the low-confidence raise, the
sample below uses raise_on_low_confidence=False (or set True to match production gate).
"""

import asyncio
import os

from backend.core.onboarding.onboarding_models import OnboardingAgentInput
from backend.core.onboarding.onboarding_orchestrator import run_onboarding_orchestrator


async def main():
    test_input = OnboardingAgentInput(
        website_url="https://neovarsityafrica.com/",
        company_name="neovarsityafrica",
    )

    if not (os.getenv("SERPER_API_KEY") or "").strip():
        print("Note: SERPER_API_KEY is unset — the Serper tool will return a clear error in the run.\n")

    print(f"Starting ORCHESTRATED onboarding for: {test_input.website_url}...")
    try:
        profile = await run_onboarding_orchestrator(
            test_input,
            max_turns=28,
            max_calls_per_tool=2,
            raise_on_low_confidence=False,
        )
        print("\n--- ICP (orchestrated) ---")
        print(f"Target type: {profile.icp.target_type} | {profile.icp}")
        print(f"Industries: {', '.join(profile.icp.industry)}")

        print("\n--- Product brief ---")
        print(f"Summary: {profile.product_brief.what_it_does}")
        print(f"Differentiators: {profile.product_brief.key_differentiators}")

        print(f"\nConfidence: {profile.confidence_score * 100:.1f}%")
        if profile.missing_fields:
            print(f"Missing: {profile.missing_fields}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
