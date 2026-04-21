"""
seed.py
-------
Seeds the local database with the exact fixture data from mock_data.py.
No agents are called. No API keys needed. No internet required.
Everything is written directly to the database from hardcoded fixtures.

What gets created per fixture:
  - 1 user
  - 1 campaign
  - 1 ICP
  - 1 product brief
  - 1 orchestration slot (inactive, pass-through)
  - leads (with status, provider data)
  - lead queries (5 per lead)
  - enrichment results (full, including discrepancies and evidence)
  - qualification results (approved / review / rejected)
  - email sequences (placeholder — real ones written by email agent)

Two fixtures are available:
  ANDELA   — AI/ML engineers ICP, 3 leads from mock_data.py
  STRIPE   — Payments/fintech ICP, same 3 leads (different campaign angle)

Usage:
  python seed.py                     seeds both fixtures
  python seed.py --fixture andela    seeds Andela only
  python seed.py --fixture stripe    seeds Stripe only
  python seed.py --reset             wipes DB + queues + storage, then re-seeds both
  python seed.py --summary           prints what is currently in the DB

After seeding, inspect with:
  sqlite3 sda_local.db ".tables"
  sqlite3 sda_local.db "SELECT id, name, status FROM campaigns;"
  sqlite3 sda_local.db "SELECT name, email, status FROM leads;"
"""

import os
import sys
import json
import shutil
import argparse
import logging

# ── Point to local environment ─────────────────────────────────────────────
os.environ.setdefault("SDA_ENV", "local")
logging.basicConfig(level=logging.WARNING)


# ── Reset singletons so fresh instances are created with correct paths ─────
def _reset_singletons():
    import importlib
    for mod_path in [
        "infrastructure.local.local_db",
        "infrastructure.local.local_queue",
        "infrastructure.local.local_storage",
    ]:
        mod = sys.modules.get(mod_path)
        if mod:
            for attr in ["_local_db", "_local_queue", "_local_storage"]:
                if hasattr(mod, attr):
                    setattr(mod, attr, None)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURE DEFINITIONS
# Taken directly from mock_data.py — no transformation, no invention
# ═══════════════════════════════════════════════════════════════════════════

# ── Users ──────────────────────────────────────────────────────────────────

FIXTURE_USERS = {
    "andela": {
        "email": "test.andela@sda-local.dev",
        "full_name": "Andela Test User",
    },
    "stripe": {
        "email": "test.stripe@sda-local.dev",
        "full_name": "Stripe Test User",
    },
}

# ── Campaigns ──────────────────────────────────────────────────────────────

FIXTURE_CAMPAIGNS = {
    "andela": {
        "name": "Andela — AI Engineers Outreach Q1",
        "website_url": "https://andela.com/",
        "company_name": "Andela",
    },
    "stripe": {
        "name": "Stripe — Fintech Product Managers Outreach Q1",
        "website_url": "https://stripe.com/",
        "company_name": "Stripe",
    },
}

# ── ICPs — taken directly from MOCK_ONBOARDING_ANDELA and MOCK_ONBOARDING_STRIPE ──

FIXTURE_ICPS = {
    "andela": {
        "target_type": "business",
        "industry": [
            "Software Development",
            "IT Services and IT Consulting",
            "Technology, Information and Internet",
        ],
        "company_size_min": 50,
        "company_size_max": 1000,
        "funding_status": None,
        "job_titles": ["CTO", "Developer", "Technical Lead"],
        "seniority": ["owner", "founder", "c_suite", "head", "director"],
        "locations": ["Global"],
        "tech_stack": None,
        "demographics": None,
        "confidence_score": 0.7,
        "missing_fields": [
            "product_brief.who_it_is_for",
            "product_brief.pain_it_solves",
        ],
    },
    "stripe": {
        "target_type": "both",
        "industry": [
            "Software Development",
            "IT Services and IT Consulting",
            "Technology, Information and Internet",
        ],
        "company_size_min": 1,
        "company_size_max": None,
        "funding_status": None,
        "job_titles": [],
        "seniority": None,
        "locations": ["Global"],
        "tech_stack": None,
        "demographics": None,
        "confidence_score": 0.9,
        "missing_fields": [],
    },
}

# ── Product Briefs — taken directly from MOCK_ONBOARDING_ANDELA and MOCK_ONBOARDING_STRIPE ──

FIXTURE_BRIEFS = {
    "andela": {
        "product_name": "Andela",
        "what_it_does": (
            "Provides companies with access to remote software developers "
            "trained and managed by Andela."
        ),
        "who_it_is_for": (
            "Technology companies and startups looking to scale their "
            "engineering teams remotely."
        ),
        "pain_it_solves": (
            "Companies struggle to find and retain qualified software engineers "
            "quickly enough to meet product development demands."
        ),
        "key_differentiators": [
            "Rigorous developer screening process",
            "Global talent pool",
            "Focus on long-term partnerships",
        ],
        "ideal_customer_description": (
            "A CTO or technical leader at a 50–1000 person tech company who needs to "
            "scale their engineering team rapidly with pre-vetted remote developers, "
            "without the overhead of traditional hiring."
        ),
    },
    "stripe": {
        "product_name": "Stripe",
        "what_it_does": (
            "Provides a comprehensive financial infrastructure platform that enables "
            "businesses to accept payments, offer financial services, and manage "
            "revenue models globally."
        ),
        "who_it_is_for": (
            "Businesses of all sizes that need to accept payments or build "
            "financial products."
        ),
        "pain_it_solves": (
            "Businesses struggle with fragmented, unreliable payment infrastructure "
            "and the complexity of managing global revenue operations across currencies "
            "and regulatory environments."
        ),
        "key_differentiators": [
            "Global payment acceptance",
            "Comprehensive financial tools",
            "Reliable uptime and security",
            "Scalable infrastructure",
        ],
        "ideal_customer_description": (
            "Any business — from solo developers to large enterprises — that processes "
            "payments online, needs to embed financial services, or wants to scale "
            "revenue operations globally without building custom infrastructure."
        ),
    },
}

# ── Leads — taken directly from MOCK_ENRICHED_LEADS ──────────────────────
# Same 3 leads used for both fixtures (different campaigns, same prospects)

FIXTURE_LEADS = [
    {
        "name": "Marshall Syahrial",
        "first_name": "Marshall",
        "last_name": "Syahrial",
        "title": "Principal Product Manager",
        "seniority": None,
        "email": "marshall.syahrial@commonsecuritization.com",
        "email_status": "VERIFIED",
        "phone": None,
        "company": "Financial Technology",
        "company_size": 341,
        "industry": "Financial Services",
        "location": "Washington",
        "country": "United States",
        "linkedin": "https://www.linkedin.com/in/marshall-s-14135b34",
        "provider_id": "aaaa22441dffd56192a0f1b2",
        "provider": "prospeo",
        "type": "business",
    },
    {
        "name": "Ar. Shamali Kather",
        "first_name": "Ar. Shamali",
        "last_name": "Kather",
        "title": "Product Manager II",
        "seniority": None,
        "email": "shamali.kather@73strings.com",
        "email_status": "VERIFIED",
        "phone": None,
        "company": "73 Strings",
        "company_size": 120,
        "industry": "Financial Services",
        "location": "Kurla",
        "country": "India",
        "linkedin": "https://www.linkedin.com/in/ar-shamali-kather-2071b7112",
        "provider_id": "aaaaec3f174cb9f57b9a3da4",
        "provider": "prospeo",
        "type": "business",
    },
    {
        "name": "Michael Greenlief",
        "first_name": "Michael",
        "last_name": "Greenlief",
        "title": "Senior Technical Product Manager",
        "seniority": None,
        "email": "michael.greenlief@jackhenry.com",
        "email_status": "VERIFIED",
        "phone": None,
        "company": "Jack Henry",
        "company_size": 6800,
        "industry": "Financial Services",
        "location": "Chicago",
        "country": "United States",
        "linkedin": "https://www.linkedin.com/in/mgreenlief00",
        "provider_id": "aaaafbeeda6ec89df2e76612",
        "provider": "prospeo",
        "type": "business",
    },
]

# ── Lead Queries — built from generate_queries.py logic ──────────────────

FIXTURE_QUERIES = [
    # Marshall Syahrial (lead index 1)
    [
        'site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
        '"Marshall Syahrial" "Principal Product Manager" "Financial Technology"',
        '"Marshall Syahrial" "Financial Technology" interview OR news OR announcement',
        '"marshall.syahrial@commonsecuritization.com" contact OR email',
        '"Marshall Syahrial" speaker OR author OR podcast "Financial Services"',
    ],
    # Ar. Shamali Kather (lead index 2)
    [
        'site:linkedin.com/in/ar-shamali-kather-2071b7112 "Ar. Shamali Kather"',
        '"Ar. Shamali Kather" "Product Manager II" "73 Strings"',
        '"Ar. Shamali Kather" "73 Strings" interview OR news OR announcement',
        '"shamali.kather@73strings.com" contact OR email',
        '"Ar. Shamali Kather" speaker OR author OR podcast "Financial Services"',
    ],
    # Michael Greenlief (lead index 3)
    [
        'site:linkedin.com/in/mgreenlief00 "Michael Greenlief"',
        '"Michael Greenlief" "Senior Technical Product Manager" "Jack Henry"',
        '"Michael Greenlief" "Jack Henry" interview OR news OR announcement',
        '"michael.greenlief@jackhenry.com" contact OR email',
        '"Michael Greenlief" speaker OR author OR podcast "Financial Services"',
    ],
]

# ── Enrichment Results — taken directly from MOCK_ENRICHMENT_OUTPUT ───────

FIXTURE_ENRICHMENTS = [
    # Lead 1: Marshall Syahrial
    {
        "lead_index": 1,
        "identity_status": "confirmed",
        "confidence_score": 0.4,
        "enriched_data": {
            "current_title": None,
            "social_links": [
                {
                    "platform": "linkedin",
                    "url": "https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
                }
            ],
            "company_signals": [
                {"key": "company_name", "value": "US Financial Technology"},
            ],
            "notable_achievements": [
                "Named Leader of the Quarter Q1 2022 at US Financial Technology",
            ],
        },
        "discrepancies": [
            {
                "field": "company",
                "original_value": "Financial Technology",
                "found_value": "US Financial Technology",
                "source_url": "https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
            }
        ],
        "raw_search_evidence": [
            {
                "query": 'site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
                "title": "Congratulations to our Q1 2022 Leaders of the Quarter | LinkedIn",
                "link": "https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
                "snippet": "Congratulations to Marshall Syahrial, named Leader of the Quarter Q1 2022 at US Financial Technology.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "linkedin.com",
            },
            {
                "query": 'site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
                "title": "Marshall Syahrial LinkedIn profile",
                "link": "https://www.linkedin.com/in/marshall-s-14135b34",
                "snippet": "Principal Product Manager at US Financial Technology. Washington, United States.",
                "position": 2,
                "result_type": "organic",
                "source": "google",
                "domain": "linkedin.com",
            },
        ],
        "evidence_used": [
            "https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
        ],
        "query_slot_coverage": [
            {"key": "Q1", "value": "LinkedIn post from US Financial Technology recognizing Marshall Syahrial as Leader of the Quarter Q1 2022."},
            {"key": "Q2", "value": "no results returned"},
            {"key": "Q3", "value": "no results returned"},
            {"key": "Q4", "value": "no results returned"},
            {"key": "Q5", "value": "no results returned"},
        ],
        "enrichment_summary": (
            "Marshall Syahrial was confirmed as a Leader of the Quarter at US Financial Technology "
            "via a LinkedIn post. Company name differs from 'Financial Technology' in source data — "
            "likely same company, abbreviated name. No job title, email, interviews, or further "
            "achievements found. Confidence is low due to partial signal and stale/private LinkedIn profile URL."
        ),
    },

    # Lead 2: Ar. Shamali Kather
    {
        "lead_index": 2,
        "identity_status": "confirmed",
        "confidence_score": 1.0,
        "enriched_data": {
            "current_title": "Product Manager II at 73 Strings",
            "social_links": [
                {
                    "platform": "linkedin",
                    "url": "https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
                }
            ],
            "company_signals": [
                {"key": "company_name", "value": "73 Strings"},
            ],
            "notable_achievements": [],
        },
        "discrepancies": [],
        "raw_search_evidence": [
            {
                "query": 'site:linkedin.com/in/ar-shamali-kather-2071b7112 "Ar. Shamali Kather"',
                "title": "Ar. Shamali Kather | LinkedIn",
                "link": "https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
                "snippet": "Product Manager II at 73 Strings. Ar. Shamali Kather posted about UI/UX design trends.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "linkedin.com",
            },
            {
                "query": '"Ar. Shamali Kather" "Product Manager II" "73 Strings"',
                "title": "Ar Kather Email & Phone Number | Product Manager II at 73 Strings | ContactOut",
                "link": "https://contactout.com/ar-shamali-kather-15918",
                "snippet": "Ar Kather's Email & Phone Number. Product Manager II at 73 Strings.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "contactout.com",
            },
            {
                "query": '"Ar. Shamali Kather" "73 Strings" interview OR news OR announcement',
                "title": "73 Strings — Product Team | The Org",
                "link": "https://theorg.com/org/73-strings/teams/product-team",
                "snippet": "The product team at 73 Strings includes Ar. Shamali Kather, Product Manager II.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "theorg.com",
            },
        ],
        "evidence_used": [
            "https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
            "https://contactout.com/ar-shamali-kather-15918",
            "https://theorg.com/org/73-strings/teams/product-team",
        ],
        "query_slot_coverage": [
            {"key": "Q1", "value": "LinkedIn profile/activity found for Ar. Shamali Kather."},
            {"key": "Q2", "value": "Confirmed title and company from LinkedIn and The Org."},
            {"key": "Q3", "value": "No news/interview/announcement results found."},
            {"key": "Q4", "value": "Contact info found on ContactOut listing for Product Manager II at 73 Strings."},
            {"key": "Q5", "value": "No speaker/author/podcast achievements found."},
        ],
        "enrichment_summary": (
            "Ar. Shamali Kather confirmed as Product Manager II at 73 Strings, with public-facing "
            "LinkedIn and The Org profiles plus appearance on ContactOut. No notable achievements "
            "surfaced and no discrepancies detected. High confidence due to cross-source confirmation."
        ),
    },

    # Lead 3: Michael Greenlief
    {
        "lead_index": 3,
        "identity_status": "confirmed",
        "confidence_score": 1.0,
        "enriched_data": {
            "current_title": "Senior Technical Product Manager for Financial Crimes Defender at Jack Henry",
            "social_links": [
                {
                    "platform": "linkedin",
                    "url": "https://www.linkedin.com/in/mgreenlief00",
                }
            ],
            "company_signals": [
                {"key": "company_name", "value": "Jack Henry"},
            ],
            "notable_achievements": [],
        },
        "discrepancies": [],
        "raw_search_evidence": [
            {
                "query": 'site:linkedin.com/in/mgreenlief00 "Michael Greenlief"',
                "title": "Michael Greenlief | LinkedIn",
                "link": "https://www.linkedin.com/in/mgreenlief00",
                "snippet": "Senior Technical Product Manager for Financial Crimes Defender at Jack Henry. Chicago, United States.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "linkedin.com",
            },
            {
                "query": '"Michael Greenlief" "Senior Technical Product Manager" "Jack Henry"',
                "title": "Michael Greenlief — Jack Henry | The Org",
                "link": "https://theorg.com/org/jack-henry-associates/org-chart/michael-greenlief",
                "snippet": "Michael Greenlief is a Senior Technical Product Manager at Jack Henry & Associates, based in Chicago.",
                "position": 1,
                "result_type": "organic",
                "source": "google",
                "domain": "theorg.com",
            },
        ],
        "evidence_used": [
            "https://www.linkedin.com/in/mgreenlief00",
            "https://theorg.com/org/jack-henry-associates/org-chart/michael-greenlief",
        ],
        "query_slot_coverage": [
            {"key": "Q1", "value": "LinkedIn profile found and confirmed title and employer."},
            {"key": "Q2", "value": "LinkedIn and The Org both confirm title, employer, and city."},
            {"key": "Q3", "value": "Jack Henry news found but no direct mention of Michael Greenlief personally."},
            {"key": "Q4", "value": "no results returned"},
            {"key": "Q5", "value": "No speaker/author/podcast achievements found."},
        ],
        "enrichment_summary": (
            "Michael Greenlief is confirmed as Senior Technical Product Manager for Financial Crimes "
            "Defender at Jack Henry via LinkedIn and The Org. City (Chicago) confirmed via LinkedIn. "
            "No notable achievements found and no discrepancies with baseline data. High confidence "
            "due to strong cross-source confirmation."
        ),
    },
]

# ── Qualification Results — taken directly from MOCK_QUALIFICATION_OUTPUT ─

FIXTURE_QUALIFICATIONS = [
    # Lead 1: Marshall Syahrial — review
    {
        "lead_index": 1,
        "lead_name": "Marshall Syahrial",
        "decision": "review",
        "decision_reason": (
            "Low enrichment confidence and discrepancy in company name reduce "
            "confidence in fit."
        ),
        "icp_match_score": 0.62,
        "match_breakdown": [
            {"dimension": "industry", "score": 0.40, "note": "Industry is Financial Technology, similar but slightly outside main target sectors."},
            {"dimension": "job_title", "score": 0.20, "note": "Title is Principal Product Manager, relevant but only partially aligned."},
            {"dimension": "seniority", "score": 0.20, "note": "Inferred seniority may be medium; not definitively senior."},
            {"dimension": "location", "score": 1.0, "note": "Location is Washington, United States, within target."},
            {"dimension": "company_size", "score": 1.0, "note": "Company size is 341, within the ICP range of 50–1000."},
            {"dimension": "type_alignment", "score": 1.0, "note": "Type is business, matching the ICP target type."},
            {"dimension": "pain_relevance", "score": 0.30, "note": "Role as Principal Product Manager at a financial technology firm suggests relevance to scaling engineering teams."},
        ],
        "blocking_issues": [],
        "review_flags": [
            "Enrichment confidence is moderate (40%) — some lead data may be inaccurate.",
            "Discrepancy on 'company': provider says 'Financial Technology', search found 'US Financial Technology'.",
        ],
        "recommended_angle": None,
    },
    # Lead 2: Ar. Shamali Kather — approved
    {
        "lead_index": 2,
        "lead_name": "Ar. Shamali Kather",
        "decision": "approved",
        "decision_reason": (
            "High fit across key ICP dimensions with a strong seniority match "
            "and relevant role."
        ),
        "icp_match_score": 0.86,
        "match_breakdown": [
            {"dimension": "industry", "score": 1.0, "note": "Industry is Financial Services, within the target sectors."},
            {"dimension": "job_title", "score": 0.80, "note": "Title is Product Manager II, compatible with technical leadership."},
            {"dimension": "seniority", "score": 0.80, "note": "Confirmed as Product Manager II, relevant for product and technical decision influence."},
            {"dimension": "location", "score": 1.0, "note": "Location is Kurla, India, within the global target."},
            {"dimension": "company_size", "score": 1.0, "note": "Company size is 120, within the ICP range of 50–1000."},
            {"dimension": "type_alignment", "score": 1.0, "note": "Type is business, matching the ICP target type."},
            {"dimension": "pain_relevance", "score": 0.90, "note": "As a product manager at a growing company, likely to feel the pain of scaling engineering teams."},
        ],
        "blocking_issues": [],
        "review_flags": [],
        "recommended_angle": (
            "As a Product Manager at a growing financial services firm, you are likely seeking "
            "efficient ways to scale your engineering team with pre-vetted remote developers "
            "to meet product demands."
        ),
    },
    # Lead 3: Michael Greenlief — review
    {
        "lead_index": 3,
        "lead_name": "Michael Greenlief",
        "decision": "review",
        "decision_reason": (
            "High company size slightly exceeds ICP, but other dimensions are a "
            "good fit with potential for interest."
        ),
        "icp_match_score": 0.76,
        "match_breakdown": [
            {"dimension": "industry", "score": 1.0, "note": "Industry is Financial Services, within the target sectors."},
            {"dimension": "job_title", "score": 0.80, "note": "Title indicates a senior product management role, relevant for technical team scaling."},
            {"dimension": "seniority", "score": 0.80, "note": "Confirmed as Senior Technical Product Manager, senior enough for engagement."},
            {"dimension": "location", "score": 1.0, "note": "Location is Chicago, United States, within target."},
            {"dimension": "company_size", "score": 0.75, "note": "Company size is 6800, above the ICP maximum, but still relevant for large-scale hiring needs."},
            {"dimension": "type_alignment", "score": 1.0, "note": "Type is business, aligning with the ICP."},
            {"dimension": "pain_relevance", "score": 0.90, "note": "As a senior manager in financial services, likely to experience pain points related to scaling engineering resources."},
        ],
        "blocking_issues": [],
        "review_flags": [
            "Company size (6800) exceeds ICP maximum (1000).",
        ],
        "recommended_angle": (
            "As a Senior Technical Product Manager at a major financial services provider, "
            "you may be exploring swift ways to augment your engineering capacity with "
            "pre-vetted remote developers."
        ),
    },
]

# ── Email Sequences — placeholder bodies, real ones written by email agent ─
# Seeded so the DB has a complete record to test against.
# Replace with real output once email agent runs.

FIXTURE_EMAIL_SEQUENCES = [
    # Lead 2: Ar. Shamali Kather — approved
    {
        "lead_index": 2,
        "lead_email": "shamali.kather@73strings.com",
        "email_1": {
            "subject": "[PLACEHOLDER] Email 1 for Ar. Shamali Kather",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "email_2": {
            "subject": "[PLACEHOLDER] Follow-up for Ar. Shamali Kather",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "email_3": {
            "subject": "[PLACEHOLDER] Final note for Ar. Shamali Kather",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "sequence_notes": "PLACEHOLDER — not yet generated by email agent.",
    },
    # Lead 3: Michael Greenlief — review (also gets emails)
    {
        "lead_index": 3,
        "lead_email": "michael.greenlief@jackhenry.com",
        "email_1": {
            "subject": "[PLACEHOLDER] Email 1 for Michael Greenlief",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "email_2": {
            "subject": "[PLACEHOLDER] Follow-up for Michael Greenlief",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "email_3": {
            "subject": "[PLACEHOLDER] Final note for Michael Greenlief",
            "body": "PLACEHOLDER — run email agent to generate real sequence.\n\n{{sender_name}}",
        },
        "sequence_notes": "PLACEHOLDER — not yet generated by email agent.",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# SEED FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def seed_fixture(fixture_name: str, db, queue, storage) -> dict:
    """
    Seeds one complete fixture into the database.
    Returns a summary dict of what was created.
    """
    from backend.core.enums import CampaignStatus, LeadStatus

    print(f"\n{'═' * 60}")
    print(f"  Seeding fixture: {fixture_name.upper()}")
    print(f"{'═' * 60}")

    created = {}

    # ── 1. User ────────────────────────────────────────────────────────────
    user_data = FIXTURE_USERS[fixture_name]
    user = db.create_user(
        email=user_data["email"],
        full_name=user_data["full_name"],
    )
    created["user_id"] = user["id"]
    print(f"  ✅ User:     {user['email']}  [{user['id'][:8]}...]")

    # ── 2. Campaign ────────────────────────────────────────────────────────
    camp_data = FIXTURE_CAMPAIGNS[fixture_name]
    campaign = db.create_campaign(
        user_id=user["id"],
        name=camp_data["name"],
        website_url=camp_data["website_url"],
        company_name=camp_data["company_name"],
    )
    created["campaign_id"] = campaign["id"]
    print(f"  ✅ Campaign: {campaign['name']}  [{campaign['id'][:8]}...]")

    # ── 3. ICP ─────────────────────────────────────────────────────────────
    icp_data = FIXTURE_ICPS[fixture_name]
    db.save_icp(campaign["id"], user["id"], icp_data)
    print(f"  ✅ ICP:      target_type={icp_data['target_type']}, "
          f"industries={len(icp_data['industry'])}, "
          f"confidence={icp_data['confidence_score']}")

    # ── 4. Product Brief ───────────────────────────────────────────────────
    brief_data = FIXTURE_BRIEFS[fixture_name]
    db.save_product_brief(campaign["id"], user["id"], brief_data)
    print(f"  ✅ Brief:    {brief_data['product_name']} — "
          f"{brief_data['key_differentiators'][0]}...")

    # ── 5. Orchestration Slot ──────────────────────────────────────────────
    db.init_orchestration_state(campaign["id"], user["id"])
    db.update_orchestration_state(campaign["id"], {
        "provider_selected": "prospeo",
        "fetch_all": 0,
        "enrich_mobile": 0,
        "target_lead_count": 25,
        "activated": 0,
        "notes": "Seeded — pass-through mode, orchestration agent not yet active.",
    })
    print(f"  ✅ Orchestration slot: provisioned (inactive pass-through)")

    # ── 6. Leads ───────────────────────────────────────────────────────────
    saved_leads = db.save_leads_batch(campaign["id"], user["id"], FIXTURE_LEADS)
    created["lead_ids"] = [l["id"] for l in saved_leads]
    print(f"  ✅ Leads:    {len(saved_leads)} leads seeded")
    for lead, saved in zip(FIXTURE_LEADS, saved_leads):
        print(f"             [{saved['id'][:8]}...] {lead['name']} "
              f"<{lead['email']}> — {lead['company']}")

    # ── 7. Lead Queries ────────────────────────────────────────────────────
    for i, (saved_lead, queries) in enumerate(zip(saved_leads, FIXTURE_QUERIES)):
        db.save_lead_queries(
            lead_id=saved_lead["id"],
            campaign_id=campaign["id"],
            user_id=user["id"],
            queries=queries,
        )
        db.update_lead_status(saved_lead["id"], LeadStatus.QUERIED)
    print(f"  ✅ Queries:  5 queries × {len(saved_leads)} leads = "
          f"{5 * len(saved_leads)} total")

    # ── 8. Enrichment Results ──────────────────────────────────────────────
    for enrichment in FIXTURE_ENRICHMENTS:
        idx = enrichment["lead_index"] - 1
        saved_lead = saved_leads[idx]

        # Offload raw evidence to storage if large
        evidence = enrichment.get("raw_search_evidence", [])
        enrichment_to_save = dict(enrichment)
        if len(evidence) > 5:
            s3_key = storage.put_enrichment_evidence(
                campaign["id"], saved_lead["id"], evidence
            )
            enrichment_to_save["raw_search_evidence"] = []
            enrichment_to_save["raw_search_evidence_s3"] = s3_key
        else:
            enrichment_to_save["raw_search_evidence_s3"] = None

        db.save_enrichment_result(
            lead_id=saved_lead["id"],
            campaign_id=campaign["id"],
            user_id=user["id"],
            enrichment=enrichment_to_save,
        )
        db.update_lead_status(saved_lead["id"], LeadStatus.ENRICHED)

        status_icon = {"confirmed": "✓", "ambiguous": "~", "not_found": "✗"}.get(
            enrichment["identity_status"], "?"
        )
        print(f"  ✅ Enriched: [{status_icon}] {FIXTURE_LEADS[idx]['name']} "
              f"— confidence={enrichment['confidence_score']:.0%}")

    # ── 9. Qualification Results ───────────────────────────────────────────
    for qual in FIXTURE_QUALIFICATIONS:
        idx = qual["lead_index"] - 1
        saved_lead = saved_leads[idx]
        db.save_qualification_result(
            lead_id=saved_lead["id"],
            campaign_id=campaign["id"],
            user_id=user["id"],
            decision=qual,
        )
        status = {
            "approved": LeadStatus.QUALIFIED,
            "review": LeadStatus.REVIEW,
            "rejected": LeadStatus.DISQUALIFIED,
        }.get(qual["decision"], LeadStatus.DISQUALIFIED)
        db.update_lead_status(saved_lead["id"], status)

        icon = {"approved": "✅", "review": "⚠️ ", "rejected": "❌"}.get(
            qual["decision"], "?"
        )
        print(f"  {icon} Qualified: {qual['lead_name']} — "
              f"{qual['decision'].upper()} (score={qual['icp_match_score']:.0%})")

    # ── 10. Email Sequences (placeholders) ────────────────────────────────
    for seq in FIXTURE_EMAIL_SEQUENCES:
        idx = seq["lead_index"] - 1
        saved_lead = saved_leads[idx]
        db.save_email_sequence(
            lead_id=saved_lead["id"],
            campaign_id=campaign["id"],
            user_id=user["id"],
            sequence=seq,
        )
        db.update_lead_status(saved_lead["id"], LeadStatus.EMAIL_WRITTEN)
        print(f"  ✅ Email seq: {seq['lead_email']} — placeholder seeded")

    # ── 11. Final Campaign Status ──────────────────────────────────────────
    db.update_campaign_status(
        campaign_id=campaign["id"],
        status=CampaignStatus.EMAIL_GENERATION_COMPLETE,
        agent="seed_script",
        from_status=CampaignStatus.CREATED,
        notes="Seeded from fixture data. Ready for pipeline testing.",
    )

    # ── 12. Summary ────────────────────────────────────────────────────────
    summary = db.get_campaign_summary(campaign["id"])
    created["summary"] = summary
    print(f"\n  📊 Summary: {json.dumps(summary, indent=4)}")

    return created


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY PRINTER
# ═══════════════════════════════════════════════════════════════════════════

def print_summary(db):
    """Print what is currently in the database."""
    from backend.config.settings import settings

    print(f"\n{'═' * 60}")
    print(f"  DATABASE SUMMARY")
    print(f"  Path: {settings.local.db_path}")
    print(f"{'═' * 60}")

    import sqlite3
    conn = sqlite3.connect(settings.local.db_path)
    conn.row_factory = sqlite3.Row

    users = conn.execute("SELECT * FROM users").fetchall()
    print(f"\n  Users ({len(users)}):")
    for u in users:
        print(f"    [{u['id'][:8]}...] {u['full_name']} <{u['email']}>")

    campaigns = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
    print(f"\n  Campaigns ({len(campaigns)}):")
    for c in campaigns:
        print(f"    [{c['id'][:8]}...] {c['name']}")
        print(f"      status={c['status']}  user={c['user_id'][:8]}...")

        leads = conn.execute(
            "SELECT name, email, status FROM leads WHERE campaign_id = ?",
            (c["id"],)
        ).fetchall()
        for lead in leads:
            print(f"      → {lead['name']} <{lead['email']}> [{lead['status']}]")

        summary_row = conn.execute(
            """SELECT
               COUNT(DISTINCT l.id) as leads,
               COUNT(DISTINCT e.id) as enriched,
               COUNT(DISTINCT q.id) as qualified,
               COUNT(DISTINCT es.id) as emails
               FROM campaigns c
               LEFT JOIN leads l ON l.campaign_id = c.id
               LEFT JOIN enrichment_results e ON e.campaign_id = c.id
               LEFT JOIN qualification_results q ON q.campaign_id = c.id
               LEFT JOIN email_sequences es ON es.campaign_id = c.id
               WHERE c.id = ?""",
            (c["id"],)
        ).fetchone()
        print(f"      leads={summary_row['leads']} enriched={summary_row['enriched']} "
              f"qualified={summary_row['qualified']} emails={summary_row['emails']}")

    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════════════════

def reset_all():
    """Wipe all local data — DB, queues, storage."""
    from config.settings import settings

    paths = [
        settings.local.db_path,
        settings.local.queue_path,
        settings.local.s3_mock_path,
    ]
    for path in paths:
        if os.path.exists(path):
            if os.path.isfile(path):
                os.unlink(path)
                print(f"  🗑  Deleted file: {path}")
            else:
                shutil.rmtree(path)
                print(f"  🗑  Deleted dir:  {path}")
        else:
            print(f"  –  Not found (skip): {path}")

    print("  ✅ Reset complete.")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Seed the SDA local database with fixture data."
    )
    parser.add_argument(
        "--fixture",
        choices=["andela", "stripe", "both"],
        default="both",
        help="Which fixture to seed (default: both)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe all local data before seeding",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print DB summary and exit — do not seed",
    )
    args = parser.parse_args()

    _reset_singletons()

    from backend.infrastructure.factory import get_db, get_queue, get_storage
    from backend.config.settings import settings

    if args.summary:
        print_summary(get_db())
        return

    if args.reset:
        print("\n🗑  Resetting local data...")
        reset_all()
        _reset_singletons()

    db = get_db()
    queue = get_queue()
    storage = get_storage()

    fixtures_to_seed = (
        ["andela", "stripe"] if args.fixture == "both" else [args.fixture]
    )

    print(f"\n🌱 SDA Local Seed Script")
    print(f"   Environment: {settings.env.value}")
    print(f"   DB path:     {settings.local.db_path}")
    print(f"   Queue path:  {settings.local.queue_path}")
    print(f"   Storage:     {settings.local.s3_mock_path}")
    print(f"   Fixtures:    {', '.join(fixtures_to_seed)}")

    results = {}
    for fixture_name in fixtures_to_seed:
        results[fixture_name] = seed_fixture(fixture_name, db, queue, storage)

    print(f"\n{'═' * 60}")
    print(f"  ✅ Seeding complete.")
    print(f"{'═' * 60}")
    print(f"\n  IDs for testing:")
    for fixture_name, created in results.items():
        print(f"\n  [{fixture_name.upper()}]")
        print(f"    user_id     = \"{created['user_id']}\"")
        print(f"    campaign_id = \"{created['campaign_id']}\"")
        print(f"    lead_ids    = {json.dumps(created['lead_ids'], indent=None)}")

    print(f"\n  Inspect with:")
    print(f"    sqlite3 {settings.local.db_path} \".tables\"")
    print(f"    sqlite3 {settings.local.db_path} \"SELECT id, name, status FROM campaigns;\"")
    print(f"    sqlite3 {settings.local.db_path} \"SELECT name, email, status FROM leads;\"")
    print(f"    python seed.py --summary\n")


if __name__ == "__main__":
    main()
