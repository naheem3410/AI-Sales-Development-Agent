"""Manual test harness for generate_queries — run from sda_platform root."""

import logging

from backend.core.query.generate_queries import LeadResult, generate_queries


def main():
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
        LeadResult(
            name="Ali Hassan",
            provider="apollo",
        ),
    ]

    output = generate_queries(test_leads)
    labels = ["B2B (full)", "B2B", "Both", "B2C", "Sparse"]
    for i, (label, lead_queries) in enumerate(zip(labels, output.results), 1):
        print(f" Lead {i} ({label}):")
        for j, q in enumerate(lead_queries.queries, 1):
            print(f"  {j}. {q}")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
