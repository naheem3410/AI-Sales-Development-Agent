# mock_data.py

from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.enrichment.enrichment_agent import (
    LeadEnrichmentAgentOutput,
    LeadEnrichmentResult,
    EnrichedProfile,
    SocialProfile,
    KeyValue,
    SearchResultItem,
    DiscrepancyFlag,
)
from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput, ICPOutput, ProductBriefOutput
from backend.core.qualification.qualification_agent import (
    QualificationBatchOutput,
    LeadDecision,
    DimensionScore,
)

# ── Mock Search Results (raw Prospeo format) ──────────────────
MOCK_SEARCH_RESULTS = [
    {
        "person": {
            "person_id": "aaaa22441dffd56192a0f1b2",
            "full_name": "Marshall Syahrial",
            "first_name": "Marshall",
            "last_name": "Syahrial",
            "current_job_title": "Principal Product Manager",
            "linkedin_url": "https://www.linkedin.com/in/marshall-s-14135b34",
            "location": {"city": "Washington", "country": "United States"},
        },
        "company": {"name": "Financial Technology"}
    },
    {
        "person": {
            "person_id": "aaaaec3f174cb9f57b9a3da4",
            "full_name": "Ar. Shamali Kather",
            "first_name": "Ar. Shamali",
            "last_name": "Kather",
            "current_job_title": "Product Manager II",
            "linkedin_url": "https://www.linkedin.com/in/ar-shamali-kather-2071b7112",
            "location": {"city": "Kurla", "country": "India"},
        },
        "company": {"name": "73 Strings"}
    },
    {
        "person": {
            "person_id": "aaaafbeeda6ec89df2e76612",
            "full_name": "Michael Greenlief",
            "first_name": "Michael",
            "last_name": "Greenlief",
            "current_job_title": "Senior Technical Product Manager",
            "linkedin_url": "https://www.linkedin.com/in/mgreenlief00",
            "location": {"city": "Chicago", "country": "United States"},
        },
        "company": {"name": "Jack Henry"}
    },
]


# ── Mock LeadResults ──────────────────────────────────────────
MOCK_ENRICHED_LEADS = [
    LeadResult(
        name="Marshall Syahrial",
        first_name="Marshall",
        last_name="Syahrial",
        title="Principal Product Manager",
        seniority=None,
        email="naheemquadri3410@gmail.com",
        email_status="VERIFIED",
        phone=None,
        company="Financial Technology",
        company_size=341,
        industry="Financial Services",
        location="Washington",
        country="United States",
        linkedin="https://www.linkedin.com/in/marshall-s-14135b34",
        provider_id="aaaa22441dffd56192a0f1b2",
        provider="prospeo",
        type="business"
    ),
    LeadResult(
        name="Ar. Shamali Kather",
        first_name="Ar. Shamali",
        last_name="Kather",
        title="Product Manager II",
        seniority=None,
        email="naheemquadri3410@gmail.com",
        email_status="VERIFIED",
        phone=None,
        company="73 Strings",
        company_size=120,
        industry="Financial Services",
        location="Kurla",
        country="India",
        linkedin="https://www.linkedin.com/in/ar-shamali-kather-2071b7112",
        provider_id="aaaaec3f174cb9f57b9a3da4",
        provider="prospeo",
        type="business"
    ),
    LeadResult(
        name="Michael Greenlief",
        first_name="Michael",
        last_name="Greenlief",
        title="Senior Technical Product Manager",
        seniority=None,
        email="michael.greenlief@jackhenry.com",
        email_status="VERIFIED",
        phone=None,
        company="Jack Henry",
        company_size=6800,
        industry="Financial Services",
        location="Chicago",
        country="United States",
        linkedin="https://www.linkedin.com/in/mgreenlief00",
        provider_id="aaaafbeeda6ec89df2e76612",
        provider="prospeo",
        type="business"
    ),
]


# ── Mock LeadEnrichmentAgentOutput ────────────────────────────
MOCK_ENRICHMENT_OUTPUT = LeadEnrichmentAgentOutput(
    enriched_leads=[

        # ── Lead 1: Marshall Syahrial ─────────────────────────
        LeadEnrichmentResult(
            lead_index=1,
            lead_name="Marshall Syahrial",
            identity_status="confirmed",
            confidence_score=0.4,
            raw_search_evidence=[
                SearchResultItem(
                    query='site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
                    title="Congratulations to our Q1 2022 Leaders of the Quarter | LinkedIn",
                    link="https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
                    snippet="Congratulations to Marshall Syahrial, named Leader of the Quarter Q1 2022 at US Financial Technology.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="linkedin.com",
                ),
                SearchResultItem(
                    query='site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
                    title="Marshall Syahrial LinkedIn profile",
                    link="https://www.linkedin.com/in/marshall-s-14135b34",
                    snippet="Principal Product Manager at US Financial Technology. Washington, United States.",
                    position=2,
                    result_type="organic",
                    source="google",
                    domain="linkedin.com",
                ),
            ],
            enriched_data=EnrichedProfile(
                current_title=None,
                social_links=[
                    SocialProfile(
                        platform="linkedin",
                        url="https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
                    )
                ],
                company_signals=[
                    KeyValue(key="company_name", value="US Financial Technology"),
                ],
                notable_achievements=[
                    "Named Leader of the Quarter Q1 2022 at US Financial Technology",
                ],
            ),
            discrepancies=[
                DiscrepancyFlag(
                    field="company",
                    original_value="Financial Technology",
                    found_value="US Financial Technology",
                    source_url="https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
                )
            ],
            query_slot_coverage=[
                KeyValue(key="Q1", value="LinkedIn post from US Financial Technology recognizing Marshall Syahrial as Leader of the Quarter Q1 2022."),
                KeyValue(key="Q2", value="no results returned"),
                KeyValue(key="Q3", value="no results returned"),
                KeyValue(key="Q4", value="no results returned"),
                KeyValue(key="Q5", value="no results returned"),
            ],
            evidence_used=[
                "https://www.linkedin.com/posts/usfintech_congratulations-to-our-q1-2022-leaders-of-activity-6930560844451758080-Cppt",
            ],
            enrichment_summary=(
                "Marshall Syahrial was confirmed as a Leader of the Quarter at US Financial Technology "
                "via a LinkedIn post. Company name differs from 'Financial Technology' in source data — "
                "likely same company, abbreviated name. No job title, email, interviews, or further "
                "achievements found. Confidence is low due to partial signal and stale/private LinkedIn profile URL."
            ),
        ),

        # ── Lead 2: Ar. Shamali Kather ────────────────────────
        LeadEnrichmentResult(
            lead_index=2,
            lead_name="Ar. Shamali Kather",
            identity_status="confirmed",
            confidence_score=1.0,
            raw_search_evidence=[
                SearchResultItem(
                    query='site:linkedin.com/in/ar-shamali-kather-2071b7112 "Ar. Shamali Kather"',
                    title="Ar. Shamali Kather | LinkedIn",
                    link="https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
                    snippet="Product Manager II at 73 Strings. Ar. Shamali Kather posted about UI/UX design trends.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="linkedin.com",
                ),
                SearchResultItem(
                    query='"Ar. Shamali Kather" "Product Manager II" "73 Strings"',
                    title="Ar Kather Email & Phone Number | Product Manager II at 73 Strings | ContactOut",
                    link="https://contactout.com/ar-shamali-kather-15918",
                    snippet="Ar Kather's Email & Phone Number. Product Manager II at 73 Strings.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="contactout.com",
                ),
                SearchResultItem(
                    query='"Ar. Shamali Kather" "73 Strings" interview OR news OR announcement',
                    title="73 Strings — Product Team | The Org",
                    link="https://theorg.com/org/73-strings/teams/product-team",
                    snippet="The product team at 73 Strings includes Ar. Shamali Kather, Product Manager II.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="theorg.com",
                ),
            ],
            enriched_data=EnrichedProfile(
                current_title="Product Manager II at 73 Strings",
                social_links=[
                    SocialProfile(
                        platform="linkedin",
                        url="https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
                    )
                ],
                company_signals=[
                    KeyValue(key="company_name", value="73 Strings"),
                ],
                notable_achievements=[],
            ),
            discrepancies=[],
            query_slot_coverage=[
                KeyValue(key="Q1", value="LinkedIn profile/activity found for Ar. Shamali Kather."),
                KeyValue(key="Q2", value="Confirmed title and company from LinkedIn and The Org."),
                KeyValue(key="Q3", value="No news/interview/announcement results found."),
                KeyValue(key="Q4", value="Contact info found on ContactOut listing for Product Manager II at 73 Strings."),
                KeyValue(key="Q5", value="No speaker/author/podcast achievements found."),
            ],
            evidence_used=[
                "https://www.linkedin.com/posts/ar-shamali-kather-2071b7112_ui-ux-designer-activity-7112397868325347330-Dtaa?trk=public_profile_share_view",
                "https://contactout.com/ar-shamali-kather-15918",
                "https://theorg.com/org/73-strings/teams/product-team",
            ],
            enrichment_summary=(
                "Ar. Shamali Kather confirmed as Product Manager II at 73 Strings, with public-facing "
                "LinkedIn and The Org profiles plus appearance on ContactOut. No notable achievements "
                "surfaced and no discrepancies detected. High confidence due to cross-source confirmation."
            ),
        ),

        # ── Lead 3: Michael Greenlief ─────────────────────────
        LeadEnrichmentResult(
            lead_index=3,
            lead_name="Michael Greenlief",
            identity_status="confirmed",
            confidence_score=1.0,
            raw_search_evidence=[
                SearchResultItem(
                    query='site:linkedin.com/in/mgreenlief00 "Michael Greenlief"',
                    title="Michael Greenlief | LinkedIn",
                    link="https://www.linkedin.com/in/mgreenlief00",
                    snippet="Senior Technical Product Manager for Financial Crimes Defender at Jack Henry. Chicago, United States.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="linkedin.com",
                ),
                SearchResultItem(
                    query='"Michael Greenlief" "Senior Technical Product Manager" "Jack Henry"',
                    title="Michael Greenlief — Jack Henry | The Org",
                    link="https://theorg.com/org/jack-henry-associates/org-chart/michael-greenlief",
                    snippet="Michael Greenlief is a Senior Technical Product Manager at Jack Henry & Associates, based in Chicago.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="theorg.com",
                ),
                SearchResultItem(
                    query='"Michael Greenlief" "Jack Henry" interview OR news OR announcement',
                    title="Jack Henry Annual Report — Product Team",
                    link="https://www.linkedin.com/posts/evergreen-bank-group_our-evergreen-bank-team-enjoyed-this-years-activity-7138927817458688000-xAFU",
                    snippet="Jack Henry product team activities. No direct mention of Michael Greenlief.",
                    position=1,
                    result_type="organic",
                    source="google",
                    domain="linkedin.com",
                ),
            ],
            enriched_data=EnrichedProfile(
                current_title="Senior Technical Product Manager for Financial Crimes Defender at Jack Henry",
                social_links=[
                    SocialProfile(
                        platform="linkedin",
                        url="https://www.linkedin.com/in/mgreenlief00",
                    )
                ],
                company_signals=[
                    KeyValue(key="company_name", value="Jack Henry"),
                ],
                notable_achievements=[],
            ),
            discrepancies=[],
            query_slot_coverage=[
                KeyValue(key="Q1", value="LinkedIn profile found and confirmed title and employer."),
                KeyValue(key="Q2", value="LinkedIn and The Org both confirm title, employer, and city."),
                KeyValue(key="Q3", value="Jack Henry news found but no direct mention of Michael Greenlief personally."),
                KeyValue(key="Q4", value="no results returned"),
                KeyValue(key="Q5", value="No speaker/author/podcast achievements found."),
            ],
            evidence_used=[
                "https://www.linkedin.com/in/mgreenlief00",
                "https://theorg.com/org/jack-henry-associates/org-chart/michael-greenlief",
            ],
            enrichment_summary=(
                "Michael Greenlief is confirmed as Senior Technical Product Manager for Financial Crimes "
                "Defender at Jack Henry via LinkedIn and The Org. City (Chicago) confirmed via LinkedIn. "
                "No notable achievements found and no discrepancies with baseline data. High confidence "
                "due to strong cross-source confirmation."
            ),
        ),
    ]
)


# ── Mock OnboardingAgentOutput: Stripe ────────────────────────
MOCK_ONBOARDING_STRIPE = OnboardingAgentOutput(
    icp=ICPOutput(
        target_type="both",
        industry=[
            "Software Development",
            "IT Services and IT Consulting",
            "Technology, Information and Internet",
        ],
        company_size_min=1,
        company_size_max=None,
        funding_status=None,
        job_titles=[],
        locations=["Global"],
        tech_stack=None,
        demographics=None,
        seniority=None,
    ),
    product_brief=ProductBriefOutput(
        product_name="Stripe",
        what_it_does=(
            "Provides a comprehensive financial infrastructure platform that enables businesses "
            "to accept payments, offer financial services, and manage revenue models globally."
        ),
        who_it_is_for="Businesses of all sizes that need to accept payments or build financial products.",
        pain_it_solves=(
            "Businesses struggle with fragmented, unreliable payment infrastructure and the complexity "
            "of managing global revenue operations across currencies and regulatory environments."
        ),
        key_differentiators=[
            "Global payment acceptance",
            "Comprehensive financial tools",
            "Reliable uptime and security",
            "Scalable infrastructure",
        ],
        ideal_customer_description=(
            "Any business — from solo developers to large enterprises — that processes payments online, "
            "needs to embed financial services, or wants to scale revenue operations globally without "
            "building custom infrastructure."
        ),
    ),
    confidence_score=0.9,
    missing_fields=[],
)


# ── Mock OnboardingAgentOutput: Andela ────────────────────────
MOCK_ONBOARDING_ANDELA = OnboardingAgentOutput(
    icp=ICPOutput(
        target_type="business",
        industry=[
            "Software Development",
            "IT Services and IT Consulting",
            "Technology, Information and Internet",
        ],
        company_size_min=50,
        company_size_max=1000,
        funding_status=None,
        job_titles=["CTO", "Developer", "Technical Lead"],
        locations=["Global"],
        tech_stack=None,
        demographics=None,
        seniority=["owner", "founder", "c_suite", "head", "director"],
    ),
    product_brief=ProductBriefOutput(
        product_name="Andela",
        what_it_does=(
            "Provides companies with access to remote software developers trained and managed by Andela."
        ),
        who_it_is_for="Technology companies and startups looking to scale their engineering teams remotely.",
        pain_it_solves=(
            "Companies struggle to find and retain qualified software engineers quickly enough "
            "to meet product development demands."
        ),
        key_differentiators=[
            "Rigorous developer screening process",
            "Global talent pool",
            "Focus on long-term partnerships",
        ],
        ideal_customer_description=(
            "A CTO or technical leader at a 50–1000 person tech company who needs to scale their "
            "engineering team rapidly with pre-vetted remote developers, without the overhead of "
            "traditional hiring."
        ),
    ),
    confidence_score=0.7,
    missing_fields=[
        "product_brief.who_it_is_for",
        "product_brief.pain_it_solves",
    ],
)

MOCK_QUALIFICATION_OUTPUT = QualificationBatchOutput(
    approved=[
        LeadDecision(
            lead_index=2,
            lead_name="Ar. Shamali Kather",
            decision="approved",
            decision_reason="High fit across key ICP dimensions with a strong seniority match and relevant role.",
            icp_match_score=0.86,
            match_breakdown=[
                DimensionScore(dimension="industry", score=1.0, note="Industry is Financial Services, within the target sectors."),
                DimensionScore(dimension="job_title", score=0.80, note="Title is Product Manager II, compatible with technical leadership."),
                DimensionScore(dimension="seniority", score=0.80, note="Confirmed as Product Manager II, relevant for product and technical decision influence."),
                DimensionScore(dimension="location", score=1.0, note="Location is Kurla, India, within the global target."),
                DimensionScore(dimension="company_size", score=1.0, note="Company size is 120, within the ICP range of 50–1000."),
                DimensionScore(dimension="type_alignment", score=1.0, note="Type is business, matching the ICP target type."),
                DimensionScore(dimension="pain_relevance", score=0.90, note="As a product manager at a growing company, likely to feel the pain of scaling engineering teams."),
            ],
            blocking_issues=[],
            review_flags=[],
            recommended_angle=(
                "As a Product Manager at a growing financial services firm, you are likely seeking "
                "efficient ways to scale your engineering team with pre-vetted remote developers "
                "to meet product demands."
            ),
        ),
    ],
    review=[
        LeadDecision(
            lead_index=3,
            lead_name="Michael Greenlief",
            decision="review",
            decision_reason="High company size slightly exceeds ICP, but other dimensions are a good fit with potential for interest.",
            icp_match_score=0.76,
            match_breakdown=[
                DimensionScore(dimension="industry", score=1.0, note="Industry is Financial Services, within the target sectors."),
                DimensionScore(dimension="job_title", score=0.80, note="Title indicates a senior product management role, relevant for technical team scaling."),
                DimensionScore(dimension="seniority", score=0.80, note="Confirmed as Senior Technical Product Manager, senior enough for engagement."),
                DimensionScore(dimension="location", score=1.0, note="Location is Chicago, United States, within target."),
                DimensionScore(dimension="company_size", score=0.75, note="Company size is 6800, above the ICP maximum, but still relevant for large-scale hiring needs."),
                DimensionScore(dimension="type_alignment", score=1.0, note="Type is business, aligning with the ICP."),
                DimensionScore(dimension="pain_relevance", score=0.90, note="As a senior manager in financial services, likely to experience pain points related to scaling engineering resources."),
            ],
            blocking_issues=[],
            review_flags=["Company size (6800) exceeds ICP maximum (1000)."],
            recommended_angle=(
                "As a Senior Technical Product Manager at a major financial services provider, "
                "you may be exploring swift ways to augment your engineering capacity with "
                "pre-vetted remote developers."
            ),
        ),
        LeadDecision(
            lead_index=1,
            lead_name="Marshall Syahrial",
            decision="review",
            decision_reason="Low enrichment confidence and discrepancy in company name reduce confidence in fit.",
            icp_match_score=0.62,
            match_breakdown=[
                DimensionScore(dimension="industry", score=0.40, note="Industry is Financial Technology, similar but slightly outside main target sectors."),
                DimensionScore(dimension="job_title", score=0.20, note="Title is Principal Product Manager, relevant but only partially aligned."),
                DimensionScore(dimension="seniority", score=0.20, note="Inferred seniority may be medium; not definitively senior."),
                DimensionScore(dimension="location", score=1.0, note="Location is Washington, United States, within target."),
                DimensionScore(dimension="company_size", score=1.0, note="Company size is 341, within the ICP range of 50–1000."),
                DimensionScore(dimension="type_alignment", score=1.0, note="Type is business, matching the ICP target type."),
                DimensionScore(dimension="pain_relevance", score=0.30, note="Role as Principal Product Manager at a financial technology firm suggests relevance to scaling engineering teams."),
            ],
            blocking_issues=[],
            review_flags=[
                "Enrichment confidence is moderate (40%) — some lead data may be inaccurate.",
                "Discrepancy on 'company': provider says 'Financial Technology', search found 'US Financial Technology'.",
            ],
            recommended_angle=None,
        ),
    ],
    rejected=[],
    batch_summary=(
        "3 leads evaluated against Andela ICP. 1 approved (Lead 2), 2 in review (Leads 1 and 3). "
        "No hard rejections. Common review reasons: company size above ICP ceiling (Lead 3) and "
        "low enrichment confidence with company name discrepancy (Lead 1). "
        "Industry scoring for Financial Services leads warrants human verification against the "
        "Software Development / IT Services ICP."
    ),
)

