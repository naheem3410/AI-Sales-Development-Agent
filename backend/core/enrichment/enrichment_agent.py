import asyncio
import httpx
import logging
import os
from typing import Any, Dict, List, Optional, Literal
from urllib.parse import urlparse

from agents import Agent, Runner, function_tool, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel, Field, ValidationError

from core.ingestion.lead_ingestion import LeadResult
from core.query.generate_queries import QueryGeneratorOutput, LeadQueries

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import re


# Models

class KeyValue(BaseModel):
    key: str
    value: str


class SocialProfile(BaseModel):
    platform: Literal["linkedin", "twitter", "github", "website", "other"]
    url: str


class SearchResultItem(BaseModel):
    query: str
    title: Optional[str] = None
    link: Optional[str] = None
    snippet: Optional[str] = None
    position: Optional[int] = None
    result_type: Optional[Literal[
        "organic",
        "knowledge_graph",
        "people_also_ask",
        "related_search",
        "sitelink",
        "other"
    ]] = None
    source: Optional[str] = None
    domain: Optional[str] = None
    extra_metadata: List[KeyValue] = Field(default_factory=list)


class DiscrepancyFlag(BaseModel):
    field: str = Field(description="The lead field that differs (e.g. 'company', 'title').")
    original_value: str = Field(description="Value from the original LeadResult.")
    found_value: str = Field(description="Value found in search results.")
    source_url: str = Field(description="URL of the result that surfaced the discrepancy.")


class EnrichedProfile(BaseModel):
    current_title: Optional[str] = None
    social_links: List[SocialProfile] = Field(default_factory=list)
    company_signals: List[KeyValue] = Field(
        default_factory=list,
        description=(
            "Only include signals with real values found in search results. "
            "NEVER use 'Unknown', 'N/A', or empty strings — omit the key entirely if not found."
        )
    )
    notable_achievements: List[str] = Field(default_factory=list)


class LeadEnrichmentResult(BaseModel):
    lead_index: int
    lead_name: str
    raw_search_evidence: List[SearchResultItem] = Field(
        description=(
            "EVERY SearchResultItem returned by the tool across all queries. "
            "Do not filter, merge, or drop any item."
        )
    )
    enriched_data: EnrichedProfile
    discrepancies: List[DiscrepancyFlag] = Field(
        default_factory=list,
        description=(
            "Any field where the search results contradict or differ from the original lead data. "
            "Always check: name, company, title, location against what was found."
        )
    )
    query_slot_coverage: List[KeyValue] = Field(
        default_factory=list,
        description=(
            "One entry per query slot (Q1–Q5) reporting what was found or 'no results'. "
            "Key = 'Q1' through 'Q5', value = brief description of what the query returned."
        )
    )
    identity_status: Literal["confirmed", "ambiguous", "not_found"] = Field(
        description=(
            "'confirmed' = one person uniquely identified. "
            "'ambiguous' = multiple people found with the same name. "
            "'not_found' = no relevant results returned."
        )
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Confidence that the enriched data is accurate and grounded. "
            "1.0: LinkedIn confirmed + company verified + multiple corroborating sources. "
            "0.7: LinkedIn found, title confirmed, company partially verified. "
            "0.5: Ambiguous identity — multiple people found, cannot uniquely identify. "
            "0.2: Name found but role/company unclear. "
            "0.0: No results at all. "
            "NOTE: 'ambiguous' identity should score ~0.5, not 0.1 — data WAS found, "
            "just not uniquely attributable."
        )
    )
    evidence_used: List[str] = Field(
        default_factory=list,
        description=(
            "URLs from raw_search_evidence that directly support enriched_data claims. "
            "Only include URLs that appear verbatim in raw_search_evidence."
        )
    )
    enrichment_summary: str = Field(
        description=(
            "Structured summary covering: (1) what was confirmed with source, "
            "(2) what was not found per query slot, (3) any discrepancies vs original lead data, "
            "(4) confidence rationale."
        )
    )


class LeadEnrichmentAgentOutput(BaseModel):
    enriched_leads: List[LeadEnrichmentResult]

# Environment variables

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_BASE_URL = os.getenv("SERPER_BASE_URL", "https://google.serper.dev/search")

if not SERPER_API_KEY:
    raise ValueError("Missing SERPER_API_KEY")


# Helper functions

def extract_domain(url: Optional[str]) -> Optional[str]:
    try:
        return urlparse(url).netloc if url else None
    except Exception:
        return None


# Normalize Serper results

def normalize_serper_results(
    raw_results: List[Dict[str, Any]],
    queries: List[str],
) -> tuple[List[SearchResultItem], Dict[str, int]]:
    """
    Returns (normalized_items, query_result_counts).
    query_result_counts maps query string → total items returned.
    """
    items: List[SearchResultItem] = []
    query_result_counts: Dict[str, int] = {}

    for res in raw_results:
        query = res.get("searchParameters", {}).get("q", "")
        count_before = len(items)

        kg = res.get("knowledgeGraph")
        if kg:
            metadata = []
            for k in ["title", "type", "description", "website", "imageUrl"]:
                if k in kg:
                    metadata.append(KeyValue(key=k, value=str(kg[k])))
            for k, v in kg.get("attributes", {}).items():
                metadata.append(KeyValue(key=k, value=str(v)))
            items.append(SearchResultItem(
                query=query,
                title=kg.get("title"),
                link=kg.get("website"),
                result_type="knowledge_graph",
                domain=extract_domain(kg.get("website")),
                extra_metadata=metadata,
            ))

        for r in res.get("organic", []):
            items.append(SearchResultItem(
                query=query,
                title=r.get("title"),
                link=r.get("link"),
                snippet=r.get("snippet"),
                position=r.get("position"),
                result_type="organic",
                source="google",
                domain=extract_domain(r.get("link")),
            ))
            for s in r.get("sitelinks", []):
                items.append(SearchResultItem(
                    query=query,
                    title=s.get("title"),
                    link=s.get("link"),
                    result_type="sitelink",
                    domain=extract_domain(s.get("link")),
                ))

        for p in res.get("peopleAlsoAsk", []):
            items.append(SearchResultItem(
                query=query,
                title=p.get("question"),
                snippet=p.get("snippet"),
                link=p.get("link"),
                result_type="people_also_ask",
                domain=extract_domain(p.get("link")),
            ))

        for r in res.get("relatedSearches", []):
            items.append(SearchResultItem(
                query=query,
                title=r.get("query"),
                result_type="related_search",
            ))

        query_result_counts[query] = len(items) - count_before

    logger.info(f"Normalized {len(items)} items from {len(raw_results)} Serper responses")
    return items, query_result_counts

# Search Serper bulk

@function_tool
async def search_serper_bulk(queries: List[str]) -> List[SearchResultItem]:
    """
    Execute a bulk Google search via Serper.dev for up to 10 queries at once.
    Returns a flat normalized list of SearchResultItem covering organic results,
    knowledge graph, people-also-ask, sitelinks, and related searches.
    Call ONCE per lead with all 5 queries.
    """
    if not queries:
        logger.warning("search_serper_bulk called with empty queries list")
        return []

    logger.info(f"[Serper] Sending {len(queries)} queries: {queries}")

    payload = [{"q": q} for q in queries]
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SERPER_BASE_URL,
            headers=headers,
            json=payload,
            timeout=45.0,
        )
        response.raise_for_status()
        raw_results = response.json()

    if not isinstance(raw_results, list):
        logger.error(f"[Serper] Unexpected response format: {type(raw_results)}")
        return []

    for i, r in enumerate(raw_results):
        organic_count = len(r.get("organic", []))
        has_kg = "knowledgeGraph" in r
        logger.info(
            f"[Serper] Query {i+1}: {organic_count} organic results, "
            f"KG={'yes' if has_kg else 'no'}, "
            f"PAA={len(r.get('peopleAlsoAsk', []))}"
        )

    normalized, query_counts = normalize_serper_results(raw_results, queries)

    # --- Fallback: retry site: queries that returned 0 results ---
    retry_queries = []
    retry_map: Dict[str, str] = {}  # fallback_query → original_query

    for query in queries:
        if query.startswith("site:") and query_counts.get(query, 0) == 0:
            # Build fallback: extract name from the site: query
            # Format: site:linkedin.com/in/<handle> "Name"
            parts = query.split('"')
            name = parts[1] if len(parts) >= 2 else None
            if name:
                fallback = f'"{name}" LinkedIn profile'
                retry_queries.append(fallback)
                retry_map[fallback] = query
                logger.info(
                    f"[Serper] site: query returned 0 results, "
                    f"queuing fallback: {fallback}"
                )

    if retry_queries:
        logger.info(f"[Serper] Sending {len(retry_queries)} fallback queries: {retry_queries}")
        retry_payload = [{"q": q} for q in retry_queries]

        async with httpx.AsyncClient() as client:
            retry_response = await client.post(
                SERPER_BASE_URL,
                headers=headers,
                json=retry_payload,
                timeout=45.0,
            )
            retry_response.raise_for_status()
            retry_raw = retry_response.json()

        for i, r in enumerate(retry_raw):
            organic_count = len(r.get("organic", []))
            logger.info(f"[Serper] Fallback query {i+1}: {organic_count} organic results")

        fallback_items, _ = normalize_serper_results(retry_raw, retry_queries)
        normalized.extend(fallback_items)
        logger.info(f"[Serper] After fallback: {len(normalized)} total items")

    logger.info(f"[Serper] Total normalized items: {len(normalized)}")
    return normalized

# Enrichment instructions

ENRICHMENT_INSTRUCTIONS = """
You are a Lead Enrichment Specialist. Search for leads and extract structured data 
strictly from what the tool returns.

== TOOL USAGE ==
- Call `search_serper_bulk` ONCE per lead with ALL 5 queries as a list.
- Do NOT split queries across multiple calls for the same lead.
- Do NOT call the tool more than once per lead.

== raw_search_evidence — CRITICAL ==
- Capture EVERY item the tool returns: organic, knowledge_graph, people_also_ask, sitelink, related_search.
- Do NOT filter, truncate, merge, or drop any item.
- Do NOT modify titles, links, or snippets.
- A lead with 5 queries should typically produce 10–50 raw_search_evidence items.

== EXTRACTION RULES ==

1. current_title
   - Prefer LinkedIn or official company page snippets.
   - Format: "Job Title at Company Name"
   - Leave null if not found — do NOT guess.

2. social_links
   - Only include URLs that appear verbatim in the tool output.
   - LinkedIn, Twitter/X, GitHub, personal site, other platforms.

3. company_signals
   - ONLY populate with real values found in results.
   - NEVER use "Unknown", "N/A", "none", or empty string — omit the key.
   - Prioritize: knowledge_graph metadata > LinkedIn company page > Crunchbase/news.
   - Keys to extract when found: company_name, industry, headquarters, founded,
     company_size, ceo, founders, parent_company, company_type, stock_ticker.

4. notable_achievements
   - Plain text strings only — NO URLs embedded in the achievement string.
   - Format: "Spoke at FinTech Summit 2023" not "Spoke at FinTech Summit (https://...)"
   - The URL goes into evidence_used, not into the achievement text.
   - Only from explicit evidence: talks, podcasts, articles, awards, press mentions.
   - Do NOT infer or assume.

5. discrepancies — ALWAYS CHECK
   - Compare found data against the original lead fields provided in the prompt.
   - Check: name spelling, company name, job title, location.
   - If search returns a different company name than the lead's known company → flag it.
   - Format: field, original_value, found_value, source_url.

6. query_slot_coverage
   - One KeyValue per query: key="Q1" through "Q5".
   - Value = brief description of what was found, or "no results returned".
   - This is mandatory — always produce 5 entries.

7. confidence_score (0.0–1.0)
   - 1.0: LinkedIn confirmed + company verified + multiple corroborating sources
   - 0.7: LinkedIn found, title confirmed, company partially verified
   - 0.4: Name found but role/company unclear or contradictory
   - 0.1: Very little or no relevant results

8. evidence_used
   - Only URLs present verbatim in raw_search_evidence.
   - Must directly support a claim in enriched_data.

== ANTI-HALLUCINATION ==
- NEVER invent URLs, snippets, or domains.
- NEVER fill company_signals with "Unknown" — omit missing fields.
- evidence_used must only contain URLs from raw_search_evidence.
- If a query returns nothing useful, state that in query_slot_coverage.

== OUTPUT ==
- One LeadEnrichmentResult per lead, in input order.
- lead_index is 1-based.
"""


# Run lead enrichment agent

async def run_lead_enrichment_agent(
    leads: List[LeadResult],
    query_output: QueryGeneratorOutput,
) -> LeadEnrichmentAgentOutput:

    model = LitellmModel(model="openai/gpt-4.1-nano")

    agent = Agent(
        name="EnrichmentAgent",
        instructions=ENRICHMENT_INSTRUCTIONS,
        tools=[search_serper_bulk],
        model=model,
        output_type=LeadEnrichmentAgentOutput,
    )

    prompt_parts = [
        f"Enrich {len(leads)} leads using the provided queries.\n",
        "For each lead, call search_serper_bulk ONCE with all 5 queries.\n",
        "Capture ALL tool results into raw_search_evidence — do not filter or truncate.\n",
        "Compare found data against the known lead fields and flag any discrepancies.\n",
        "notable_achievements must be plain text only — no URLs in the string.\n\n",
    ]

    for i, (lead, q_res) in enumerate(zip(leads, query_output.results), 1):
        name = lead.name or f"{lead.first_name or ''} {lead.last_name or ''}".strip() or f"Lead {i}"
        prompt_parts.append(f"LEAD {i}: {name}")
        if lead.company:
            prompt_parts.append(f"  Known company: {lead.company}")
        if lead.title:
            prompt_parts.append(f"  Known title: {lead.title}")
        if lead.location:
            prompt_parts.append(f"  Known location: {lead.location}")
        if lead.industry:
            prompt_parts.append(f"  Known industry: {lead.industry}")
        prompt_parts.append("  Queries (pass all 5 to search_serper_bulk):")
        for j, q in enumerate(q_res.queries, 1):
            prompt_parts.append(f"    Q{j}: {q}")
        prompt_parts.append("")

    prompt = "\n".join(prompt_parts)
    logger.info(f"[EnrichmentAgent] Starting for {len(leads)} lead(s)")

    try:
        result = await Runner.run(agent, prompt, max_turns=len(leads) * 4)
    except MaxTurnsExceeded:
        logger.error("[EnrichmentAgent] Max turns exceeded")
        return LeadEnrichmentAgentOutput(enriched_leads=[])

    try:
        if isinstance(result.final_output, str):
            output = LeadEnrichmentAgentOutput.model_validate_json(result.final_output)
        else:
            output = LeadEnrichmentAgentOutput.model_validate(result.final_output)
    except ValidationError as e:
        logger.error(f"[EnrichmentAgent] Validation error: {e.json()}")
        raise

    url_pattern = re.compile(r'https?://\S+')

    for enriched in output.enriched_leads:
        raw_urls = {item.link for item in enriched.raw_search_evidence if item.link}

        # 1. Strip hallucinated evidence_used URLs
        hallucinated = [u for u in enriched.evidence_used if u not in raw_urls]
        if hallucinated:
            logger.warning(
                f"[EnrichmentAgent] Lead {enriched.lead_index}: "
                f"Removing {len(hallucinated)} hallucinated URL(s): {hallucinated}"
            )
            enriched.evidence_used = [u for u in enriched.evidence_used if u in raw_urls]

        # 2. Scrub empty/unknown company_signals
        before = len(enriched.enriched_data.company_signals)
        enriched.enriched_data.company_signals = [
            kv for kv in enriched.enriched_data.company_signals
            if kv.value.strip().lower() not in ("unknown", "n/a", "", "none")
        ]
        removed = before - len(enriched.enriched_data.company_signals)
        if removed:
            logger.info(
                f"[EnrichmentAgent] Lead {enriched.lead_index}: "
                f"Scrubbed {removed} empty/unknown company_signal(s)"
            )

        # 3. Strip URLs embedded in notable_achievements strings
        clean_achievements = []
        for achievement in enriched.enriched_data.notable_achievements:
            cleaned = url_pattern.sub("", achievement).strip().rstrip("()")
            if cleaned:
                clean_achievements.append(cleaned)
        enriched.enriched_data.notable_achievements = clean_achievements

        # 4. Enforce query_slot_coverage has exactly 5 entries
        if len(enriched.query_slot_coverage) != 5:
            logger.warning(
                f"[EnrichmentAgent] Lead {enriched.lead_index}: "
                f"query_slot_coverage has {len(enriched.query_slot_coverage)} entries, expected 5"
            )

        # 5. Log summary
        logger.info(
            f"[EnrichmentAgent] Lead {enriched.lead_index} '{enriched.lead_name}': "
            f"status={enriched.identity_status}, "
            f"confidence={enriched.confidence_score:.2f}, "
            f"raw_evidence={len(enriched.raw_search_evidence)}, "
            f"discrepancies={len(enriched.discrepancies)}"
        )

    logger.info(f"[EnrichmentAgent] Done. {len(output.enriched_leads)} leads enriched.")
    return output


# Test enrichment pipeline

async def test_enrichment_pipeline():
    test_leads = [
        LeadResult( 
            name="Marshall Syahrial",
            title="Principal Product Manager",
            email="marshall.syahrial@commonsecuritization.com",
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
            email="shamali.kather@73strings.com",
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
        LeadQueries(queries=[
            'site:linkedin.com/in/marshall-s-14135b34 "Marshall Syahrial"',
            '"Marshall Syahrial" "Principal Product Manager" "Financial Technology"',
            '"Marshall Syahrial" "Financial Technology" interview OR news OR announcement',
            '"marshall.syahrial@commonsecuritization.com" contact OR email',
            '"Marshall Syahrial" speaker OR author OR podcast "Financial Services"',
        ]),
        LeadQueries(queries=[
            'site:linkedin.com/in/ar-shamali-kather-2071b7112 "Ar. Shamali Kather"',
            '"Ar. Shamali Kather" "Product Manager II" "73 Strings"',
            '"Ar. Shamali Kather" "73 Strings" interview OR news OR announcement',
            '"shamali.kather@73strings.com" contact OR email',
            '"Ar. Shamali Kather" speaker OR author OR podcast "Financial Services"',
        ]),
        LeadQueries(queries=[
            'site:linkedin.com/in/mgreenlief00 "Michael Greenlief"',
            '"Michael Greenlief" "Senior Technical Product Manager" "Jack Henry"',
            '"Michael Greenlief" "Jack Henry" interview OR news OR announcement',
            '"michael.greenlief@jackhenry.com" contact OR email',
            '"Michael Greenlief" speaker OR author OR podcast "Financial Services"',
        ]),
        LeadQueries(queries=[
            '"Maria Garcia" LinkedIn "Madrid"',
            '"Maria Garcia" "Madrid" occupation OR profession',
            '"Maria Garcia" "Madrid" news OR mention OR profile',
            '"maria.garcia@gmail.com" contact OR email',
            '"Maria Garcia" review OR testimonial OR mention "Madrid"',
        ]),
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
            print(f"\n Lead {res.lead_index}: {res.lead_name}  "
                f"[{status_icon} {res.identity_status}] [confidence: {res.confidence_score:.0%}]")
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