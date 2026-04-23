"""Manual test harness for email_agent — run from sda_platform root."""

import asyncio

from backend.core.email.email_agent import run_email_copywriting_agent
from backend.core.mock_data import (
    MOCK_ENRICHED_LEADS,
    MOCK_ENRICHMENT_OUTPUT,
    MOCK_QUALIFICATION_OUTPUT,
    MOCK_ONBOARDING_ANDELA,
)


async def main():
    decisions_to_write = (
        MOCK_QUALIFICATION_OUTPUT.approved + MOCK_QUALIFICATION_OUTPUT.review
    )

    enrichment_map = {
        e.lead_index: e for e in MOCK_ENRICHMENT_OUTPUT.enriched_leads
    }

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


if __name__ == "__main__":
    asyncio.run(main())
