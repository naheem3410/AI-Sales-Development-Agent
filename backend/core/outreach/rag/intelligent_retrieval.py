"""
Targeted RAG retrieval for replies and sequence generation.

Runs several small semantic searches (different query phrasings and optional
source_type filters) instead of one broad dump, merges by score, dedupes chunks,
and caps total characters so prompts stay within a sensible context budget.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from backend.core.onboarding.onboarding_agent import OnboardingAgentOutput
from backend.core.outreach.rag.rag_store import (
    RAGQueryInput,
    RetrievedChunk,
    get_rag_store,
)

logger = logging.getLogger(__name__)

# Budgets (characters, approximate token proxy)
REPLY_CONTEXT_MAX_CHARS = 7_000
SEQUENCE_CONTEXT_MAX_CHARS = 6_500
MAX_CHUNK_CHARS = 1_800


def _truncate_chunk(text: str, max_len: int = MAX_CHUNK_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rstrip() + "..."


def _merge_chunks(chunks: List[RetrievedChunk], max_total_chars: int) -> str:
    """Dedupe by chunk_id (keep best score), sort by similarity, cap total length."""
    best: Dict[str, RetrievedChunk] = {}
    for c in chunks:
        prev = best.get(c.chunk_id)
        if prev is None or c.similarity_score > prev.similarity_score:
            best[c.chunk_id] = c

    merged = sorted(best.values(), key=lambda x: -x.similarity_score)

    parts: List[str] = []
    total = 0
    sep = "\n\n---\n\n"
    for c in merged:
        body = _truncate_chunk(c.chunk_text)
        block = f"[{c.source_type.upper()} — {c.document_title}]\n{body}"
        add_len = len(block) + (len(sep) if parts else 0)
        if total + add_len > max_total_chars:
            room = max_total_chars - total - len(sep if parts else "")
            if room > 200:
                block = _truncate_chunk(
                    f"[{c.source_type.upper()} — {c.document_title}]\n{c.chunk_text}",
                    max_len=room,
                )
                parts.append(block)
            break
        parts.append(block)
        total += add_len

    text = sep.join(parts) if parts else ""
    return text.strip()


def retrieve_reply_rag_context(
    user_id: str,
    reply_body: str,
    *,
    product_name: str,
    product_pain: str,
) -> Optional[str]:
    """
    Retrieve KB snippets relevant to answering an inbound reply: policies, FAQs,
    templates, positioning — grounded in product context + lead message (not the
    whole thread).
    """
    reply_snip = (reply_body or "").strip()[:450]
    pn = (product_name or "").strip()[:120] or "product"
    pp = (product_pain or "").strip()[:220]

    store = get_rag_store()
    specs: List[Tuple[str, Optional[str], int]] = [
        (
            (
                f"Inbound sales reply. Product: {pn}. Problem solved: {pp}. "
                f"Prospect wrote: {reply_snip or '(empty message)'}"
            ),
            None,
            2,
        ),
        (
            (
                f"Email reply templates tone CTAs follow-up best practices. "
                f"Context: {pn}. Prospect snippet: {(reply_snip[:200] or 'n/a')}"
            ),
            "email_template",
            2,
        ),
        (
            (
                f"Product facts pricing features FAQs how it works. {pn}. "
                f"Question context: {reply_snip[:220] or 'general'}"
            ),
            "faq",
            2,
        ),
        (
            (
                f"Company brand voice messaging guidelines policies compliance "
                f"outreach rules. Product: {pn}"
            ),
            "company_info",
            2,
        ),
        (
            (
                f"Supplementary guidance objections handling. {pn}. "
                f"{reply_snip[:150]}"
            ),
            "other",
            1,
        ),
    ]

    all_chunks: List[RetrievedChunk] = []
    for query, st_filter, top_k in specs:
        try:
            out = store.query(
                RAGQueryInput(
                    query=query,
                    user_id=user_id,
                    top_k=top_k,
                    source_type_filter=st_filter,
                )
            )
            all_chunks.extend(out.chunks)
        except Exception as e:
            logger.warning("[RAG] Reply retrieval sub-query failed (%s): %s", st_filter, e)

    if not all_chunks:
        return None

    text = _merge_chunks(all_chunks, REPLY_CONTEXT_MAX_CHARS)
    if not text:
        return None
    logger.info(
        "[RAG] Reply context merged: %s chunks → %s chars",
        len({c.chunk_id for c in all_chunks}),
        len(text),
    )
    return text


def retrieve_sequence_rag_context(
    user_id: str,
    onboarding: OnboardingAgentOutput,
) -> Optional[str]:
    """
    Retrieve KB snippets for 3-step cold sequence writing: templates, company voice,
    product facts, policies — tailored to product brief + ICP industries.
    """
    brief = onboarding.product_brief
    icp = onboarding.icp

    ind = ", ".join(icp.industry[:4]) if icp.industry else ""
    diff_preview = ", ".join(brief.key_differentiators[:4]) if brief.key_differentiators else ""
    pn = (brief.product_name or "").strip()[:120] or "product"
    wid = (brief.what_it_does or "").strip()[:280]
    pain = (brief.pain_it_solves or "").strip()[:220]
    who = (brief.who_it_is_for or "").strip()[:200]

    store = get_rag_store()
    specs: List[Tuple[str, Optional[str], int]] = [
        (
            (
                f"B2B cold outbound email sequence: email 1 hook, email 2 follow-up, "
                f"email 3 breakup. Personalization and compliance. "
                f"Product: {pn}. Industries: {ind}. Audience: {who}"
            ),
            None,
            2,
        ),
        (
            (
                f"Email templates subject lines outreach sequences tone CTAs. "
                f"{pn}. Differentiators: {diff_preview}"
            ),
            "email_template",
            2,
        ),
        (
            (
                f"Company positioning brand voice messaging guidelines. {pn}. {wid[:180]}"
            ),
            "company_info",
            2,
        ),
        (
            (
                f"Product description FAQs proof points pain solved. {pain}. "
                f"{diff_preview}"
            ),
            "faq",
            2,
        ),
        (
            (
                f"Additional playbooks objection handling. {pn}. {who[:120]}"
            ),
            "other",
            1,
        ),
    ]

    all_chunks: List[RetrievedChunk] = []
    for query, st_filter, top_k in specs:
        try:
            out = store.query(
                RAGQueryInput(
                    query=query,
                    user_id=user_id,
                    top_k=top_k,
                    source_type_filter=st_filter,
                )
            )
            all_chunks.extend(out.chunks)
        except Exception as e:
            logger.warning("[RAG] Sequence retrieval sub-query failed (%s): %s", st_filter, e)

    if not all_chunks:
        return None

    text = _merge_chunks(all_chunks, SEQUENCE_CONTEXT_MAX_CHARS)
    if not text:
        return None
    logger.info(
        "[RAG] Sequence context merged: %s chunks → %s chars",
        len({c.chunk_id for c in all_chunks}),
        len(text),
    )
    return text
