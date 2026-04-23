"""Manual test harness for qualification_agent — run from sda_platform root."""

import asyncio

from backend.core.mock_data import MOCK_ENRICHED_LEADS, MOCK_ENRICHMENT_OUTPUT, MOCK_ONBOARDING_ANDELA
from backend.core.qualification.qualification_agent import LeadDecision, run_qualification_agent


async def main():
    print(f" Qualifying {len(MOCK_ENRICHED_LEADS)} leads...\n")
    try:
        output = await run_qualification_agent(
            leads=MOCK_ENRICHED_LEADS,
            enrichment_output=MOCK_ENRICHMENT_OUTPUT,
            onboarding=MOCK_ONBOARDING_ANDELA,
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


if __name__ == "__main__":
    asyncio.run(main())
