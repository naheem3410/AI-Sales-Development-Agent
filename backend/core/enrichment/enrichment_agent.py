import asyncio
import httpx
import logging
import os
from typing import Any, Dict, List, Optional, Literal, Tuple
from urllib.parse import urlparse

from agents import Agent, Runner, function_tool, MaxTurnsExceeded
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel, Field, ValidationError

from backend.core.ingestion.lead_ingestion import LeadResult
from backend.core.observability import agent_observe
from backend.core.enrichment.instruction import ENRICHMENT_INSTRUCTIONS
from backend.core.query.generate_queries import QueryGeneratorOutput
from backend.core.utils.llm_batch import (
    MAX_PARALLEL,
    async_run_with_retries,
    chunk_indices,
)
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def _post_process_enrichment_output(output: LeadEnrichmentAgentOutput) -> None:
    """URL scrubbing, signal cleanup, and logging on merged enrichment output."""
    url_pattern = re.compile(r"https?://\S+")

    for enriched in output.enriched_leads:
        raw_urls = {item.link for item in enriched.raw_search_evidence if item.link}

        hallucinated = [u for u in enriched.evidence_used if u not in raw_urls]
        if hallucinated:
            logger.warning(
                f"[EnrichmentAgent] Lead {enriched.lead_index}: "
                f"Removing {len(hallucinated)} hallucinated URL(s): {hallucinated}"
            )
            enriched.evidence_used = [u for u in enriched.evidence_used if u in raw_urls]

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

        clean_achievements = []
        for achievement in enriched.enriched_data.notable_achievements:
            cleaned = url_pattern.sub("", achievement).strip().rstrip("()")
            if cleaned:
                clean_achievements.append(cleaned)
        enriched.enriched_data.notable_achievements = clean_achievements

        if len(enriched.query_slot_coverage) != 5:
            logger.warning(
                f"[EnrichmentAgent] Lead {enriched.lead_index}: "
                f"query_slot_coverage has {len(enriched.query_slot_coverage)} entries, expected 5"
            )

        logger.info(
            f"[EnrichmentAgent] Lead {enriched.lead_index} '{enriched.lead_name}': "
            f"status={enriched.identity_status}, "
            f"confidence={enriched.confidence_score:.2f}, "
            f"raw_evidence={len(enriched.raw_search_evidence)}, "
            f"discrepancies={len(enriched.discrepancies)}"
        )


async def _enrich_leads_one_batch(
    leads: List[LeadResult],
    query_output: QueryGeneratorOutput,
    global_offset_0based: int,
) -> LeadEnrichmentAgentOutput:
    """Run the enrichment agent for one batch; remaps ``lead_index`` to global 1-based positions."""
    if not leads:
        return LeadEnrichmentAgentOutput(enriched_leads=[])

    model = LitellmModel(model="openai/gpt-4.1")

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
        f"Use these global lead_index values in your output for each lead, in order: "
        f"{', '.join(str(global_offset_0based + i + 1) for i in range(len(leads)))}.\n\n",
    ]

    for i, (lead, q_res) in enumerate(zip(leads, query_output.results), 1):
        name = lead.name or f"{lead.first_name or ''} {lead.last_name or ''}".strip() or f"Lead {i}"
        prompt_parts.append(f"LEAD {i} (global lead_index={global_offset_0based + i}): {name}")
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
    logger.info(
        f"[EnrichmentAgent] Batch starting at offset {global_offset_0based} "
        f"for {len(leads)} lead(s)"
    )

    try:
        result = await Runner.run(agent, prompt, max_turns=max(len(leads) * 4, 4))
    except MaxTurnsExceeded:
        logger.error("[EnrichmentAgent] Max turns exceeded for batch")
        return LeadEnrichmentAgentOutput(enriched_leads=[])

    try:
        if isinstance(result.final_output, str):
            output = LeadEnrichmentAgentOutput.model_validate_json(result.final_output)
        else:
            output = LeadEnrichmentAgentOutput.model_validate(result.final_output)
    except ValidationError as e:
        logger.error(f"[EnrichmentAgent] Validation error: {e.json()}")
        raise

    ordered = sorted(output.enriched_leads, key=lambda e: e.lead_index)[: len(leads)]
    for j, enriched in enumerate(ordered):
        enriched.lead_index = global_offset_0based + j + 1

    return LeadEnrichmentAgentOutput(enriched_leads=ordered)


@agent_observe("lead_enrichment_agent", as_type="agent")
async def run_lead_enrichment_agent(
    leads: List[LeadResult],
    query_output: QueryGeneratorOutput,
) -> LeadEnrichmentAgentOutput:
    """Batched enrichment (size 3, max 2 parallel), retries per batch, stable merge by index."""

    n_leads = len(leads)
    n_q = len(query_output.results)
    if n_q != n_leads:
        logger.warning(
            f"[EnrichmentAgent] Query count {n_q} != lead count {n_leads}; using min length."
        )
    n = min(n_leads, n_q)
    if n == 0:
        return LeadEnrichmentAgentOutput(enriched_leads=[])

    leads = leads[:n]
    query_output = QueryGeneratorOutput(results=query_output.results[:n])

    slices = chunk_indices(n)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def run_slice(
        start: int, end: int
    ) -> Tuple[int, Optional[LeadEnrichmentAgentOutput]]:
        batch_leads = leads[start:end]
        batch_q = QueryGeneratorOutput(results=query_output.results[start:end])
        async with sem:
            try:
                out = await async_run_with_retries(
                    lambda: _enrich_leads_one_batch(batch_leads, batch_q, start)
                )
                return (start, out)
            except Exception as e:
                logger.error(
                    f"[EnrichmentAgent] Batch [{start}:{end}] failed after retries: {e}"
                )
                return (start, None)

    tasks = [asyncio.create_task(run_slice(s, e)) for s, e in slices]
    resolved = await asyncio.gather(*tasks)
    resolved.sort(key=lambda x: x[0])

    merged: List[LeadEnrichmentResult] = []
    for _start, part in resolved:
        if part is None:
            continue
        merged.extend(part.enriched_leads)

    output = LeadEnrichmentAgentOutput(enriched_leads=merged)
    _post_process_enrichment_output(output)
    logger.info(f"[EnrichmentAgent] Done. {len(output.enriched_leads)} leads enriched.")
    return output