"""Manual test harness for lead_ingestion — run from sda_platform root."""

import json

from backend.core.ingestion.lead_ingestion import get_provider
from backend.core.onboarding.onboarding_agent import ICPOutput


def main():
    stripe_icp = ICPOutput(
        target_type="business",
        industry=["Financial Services", "Technology"],
        company_size_min=51,
        company_size_max=10000,
        funding_status=None,
        job_titles=["CFO", "Fintech Manager", "Product Manager"],
        seniority=["c_suite", "vp", "director", "manager"],
        locations=["Global"],
        tech_stack=None,
        demographics=None,
    )

    andela_icp = ICPOutput(
        target_type="business",
        industry=["AI/ML", "Tech services", "Software development"],
        company_size_min=50,
        company_size_max=None,
        funding_status=None,
        job_titles=["AI engineers", "Data scientists", "ML engineers", "AI team leads"],
        seniority=["owner", "founder", "c_suite", "partner", "vp", "head", "director"],
        locations=["Global"],
        tech_stack=None,
        demographics=None,
    )

    provider = get_provider("prospeo")

    leads = provider.get_leads(
        icp=stripe_icp,
        fetch_all=False,
        enrich_mobile=False,
        test_mode=True,
        use_mock=True,
    )

    print(leads)

    print("\n===== FINAL LEADS =====")
    if not leads:
        print(" No leads returned.")
    else:
        for lead in leads:
            print(json.dumps(lead.model_dump(exclude_none=True), indent=2))


if __name__ == "__main__":
    main()
