"""Manual test harness for enrichment_agent — run from sda_platform root."""

import asyncio

from backend.core.enrichment.enrichment_agent import run_lead_enrichment_agent
from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.query.generate_queries import LeadQueries, QueryGeneratorOutput


async def test_enrichment_pipeline():
    test_leads = [
        LeadResult(
            name="Marshall Syahrial",
            title="Principal Product Manager",
            email="naheemquadri3410@gmail.com",
            company="Financial Technology",
            industry="Financial Services",
            location="Washington",
            country="United States",
            linkedin="https://www.linkedin.com/in/marshall-s-14135b34",
            provider="prospeo",
            type="business",
        ),
        LeadResult(
            name="Ar. Shamali Kather",
            title="Product Manager II",
            email="naheemquadri3410@gmail.com",
            company="73 Strings",
            industry="Financial Services",
            location="Kurla",
            country="India",
            linkedin="https://www.linkedin.com/in/ar-shamali-kather-2071b7112",
            provider="prospeo",
            type="business",
        ),
        LeadResult(
            name="Michael Greenlief",
            title="Senior Technical Product Manager",
            email="michael.greenlief@jackhenry.com",
            company="Jack Henry",
            industry="Financial Services",
            location="Chicago",
            country="United States",
            linkedin="https://www.linkedin.com/in/mgreenlief00",
            provider="prospeo",
            type="both",
        ),
        LeadResult(
            name="Maria Garcia",
            location="Madrid",
            country="Spain",
            email="maria.garcia@gmail.com",
            provider="prospeo",
            type="individual",
        ),
    ]

    mock_query_results = [
        LeadQueries(
            queries=[
                'site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
                '"Marshall Syahrial" "Principal Product Manager" "Financial Technology"',
                '"Marshall Syahrial" "Financial Technology" interview OR news OR announcement',
                '"naheemquadri3410@gmail.com" contact OR email',
                '"Marshall Syahrial" speaker OR author OR podcast "Financial Services"',
            ]
        ),
        LeadQueries(
            queries=[
                'site:linkedin.com/in/ar-shamali-kather-2071b7112 "Ar. Shamali Kather"',
                '"Ar. Shamali Kather" "Product Manager II" "73 Strings"',
                '"Ar. Shamali Kather" "73 Strings" interview OR news OR announcement',
                '"naheemquadri3410@gmail.com" contact OR email',
                '"Ar. Shamali Kather" speaker OR author OR podcast "Financial Services"',
            ]
        ),
        LeadQueries(
            queries=[
                'site:linkedin.com/in/mgreenlief00 "Michael Greenlief"',
                '"Michael Greenlief" "Senior Technical Product Manager" "Jack Henry"',
                '"Michael Greenlief" "Jack Henry" interview OR news OR announcement',
                '"michael.greenlief@jackhenry.com" contact OR email',
                '"Michael Greenlief" speaker OR author OR podcast "Financial Services"',
            ]
        ),
        LeadQueries(
            queries=[
                '"Maria Garcia" LinkedIn "Madrid"',
                '"Maria Garcia" "Madrid" occupation OR profession',
                '"Maria Garcia" "Madrid" news OR mention OR profile',
                '"maria.garcia@gmail.com" contact OR email',
                '"Maria Garcia" review OR testimonial OR mention "Madrid"',
            ]
        ),
    ]

    query_output = QueryGeneratorOutput(results=mock_query_results)

    print(f"Starting enrichment for {len(test_leads)} leads...\n")

    try:
        output = await run_lead_enrichment_agent(
            leads=test_leads,
            query_output=query_output,
        )

        print("\n" + "=" * 80)
        print(" ENRICHMENT REPORT")
        print("=" * 80)

        for res in output.enriched_leads:
            p = res.enriched_data
            status_icon = {"confirmed": "✅", "ambiguous": "⚠️", "not_found": "❌"}.get(res.identity_status, "❓")
            print(
                f"\n Lead {res.lead_index}: {res.lead_name}  "
                f"[{status_icon} {res.identity_status}] [confidence: {res.confidence_score:.0%}]"
            )
            print(f" Title: {p.current_title or 'Not found'}")

            if p.social_links:
                for s in p.social_links:
                    print(f" {s.platform}: {s.url}")

            if p.company_signals:
                print(" Company signals:")
                for sig in p.company_signals:
                    print(f"   {sig.key}: {sig.value}")

            if p.notable_achievements:
                print(" Achievements:")
                for a in p.notable_achievements:
                    print(f"   - {a}")

            if res.discrepancies:
                print("  Discrepancies:")
                for d in res.discrepancies:
                    print(f"   {d.field}: '{d.original_value}' → '{d.found_value}' ({d.source_url})")

            print(" Query coverage:")
            for slot in res.query_slot_coverage:
                print(f"   {slot.key}: {slot.value}")

            if res.evidence_used:
                print(f" Evidence ({len(res.evidence_used)} URL(s)):")
                for url in res.evidence_used:
                    print(f"   {url}")

            print(f" Summary: {res.enrichment_summary}")
            print(f" Raw evidence items: {len(res.raw_search_evidence)}")
            print("-" * 40)

    except Exception as e:
        print(f" Enrichment failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_enrichment_pipeline())
