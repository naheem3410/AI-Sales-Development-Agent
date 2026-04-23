"""Manual test harness for onboarding_agent — run with `uv run python backend/core/onboarding/onboarding_agent_test.py` from sda_platform."""

import asyncio

from backend.core.onboarding.onboarding_agent import (
    OnboardingAgentInput,
    run_onboarding_agent,
)


async def main():
    test_input = OnboardingAgentInput(
        website_url="https://www.lapo-nigeria.org/",
        company_name="Lapo",
    )

    print(f"Starting onboarding for: {test_input.website_url}...")
    try:
        profile = await run_onboarding_agent(test_input)
        print("\n--- ICP Results ---")
        print(f"Target Type: {profile.icp.target_type} {profile.icp}")
        print(f"Industries: {', '.join(profile.icp.industry)}")

        print("\n--- Product Brief ---")
        print(f"Summary: {profile.product_brief.what_it_does}")
        print(f"Differentiators: {profile.product_brief.key_differentiators}")

        print(f"\nConfidence: {profile.confidence_score * 100}%")
        if profile.missing_fields:
            print(f"Missing: {profile.missing_fields}")
    except Exception as e:
        print(f" Error during onboarding: {e}")


if __name__ == "__main__":
    asyncio.run(main())
