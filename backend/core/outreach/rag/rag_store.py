"""
rag_store.py
------------
RAG (Retrieval Augmented Generation) store.

Local:      SQLite stores embeddings as JSON arrays.
            Cosine similarity search done in Python.
            Model loaded locally via sentence-transformers.

Production: SageMaker endpoint for embeddings.
            S3 Vectors for vector storage and similarity search.

Same interface in both environments — factory pattern.

Embedding model: all-MiniLM-L6-v2 from HuggingFace Hub
  - 384-dimensional embeddings
  - Runs on CPU, no GPU needed locally
  - Fast, accurate for semantic similarity

Document chunking:
  - Splits by paragraph first, then by token count if paragraph is too long
  - Target chunk size: 512 tokens (~400 words)
  - Overlap: 50 tokens between chunks for context continuity
"""

import os
import json
import uuid
import math
import logging
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from backend.infrastructure.factory import get_db
from backend.config.settings import settings

logger = logging.getLogger(__name__)

# ── Config

CHUNK_SIZE_CHARS = 1500      # target characters per chunk (~400 words)
CHUNK_OVERLAP_CHARS = 150    # overlap between chunks
TOP_K_DEFAULT = 5            # default number of chunks to retrieve
MIN_SIMILARITY = 0.25        # minimum cosine similarity to include in results

SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT", "")
SAGEMAKER_REGION = os.getenv("AWS_REGION", "us-east-1")



# INPUT / OUTPUT MODELS

class IngestDocumentInput(BaseModel):
    """Input for ingesting a document into the RAG store."""

    user_id: str = Field(..., description="User who owns this document.")
    title: str = Field(..., description="Human-readable title for the document.")
    source_type: str = Field(
        ...,
        description="Category of the document: 'faq', 'company_info', 'email_template', 'other'."
    )
    raw_content: str = Field(
        ..., min_length=10,
        description="Full text content of the document to embed and store."
    )
    file_size_bytes: Optional[int] = Field(
        None, description="Size of the original file in bytes, if applicable."
    )


class IngestDocumentOutput(BaseModel):
    """Result of ingesting a document."""

    document_id: str = Field(..., description="ID of the newly created document.")
    chunk_count: int = Field(..., description="Number of chunks created and embedded.")
    title: str = Field(..., description="Document title.")
    source_type: str = Field(..., description="Document category.")


class RetrievedChunk(BaseModel):
    """A single retrieved chunk from the RAG store."""

    chunk_id: str = Field(..., description="ID of the chunk.")
    document_id: str = Field(..., description="ID of the parent document.")
    document_title: str = Field(..., description="Title of the parent document.")
    source_type: str = Field(..., description="Category of the parent document.")
    chunk_text: str = Field(..., description="Text content of the chunk.")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Cosine similarity score between query and chunk."
    )


class RAGQueryInput(BaseModel):
    """Input for querying the RAG store."""

    query: str = Field(..., description="Natural language query to search for.")
    user_id: str = Field(..., description="User ID — only searches their documents.")
    top_k: int = Field(
        TOP_K_DEFAULT, ge=1, le=20,
        description="Maximum number of chunks to retrieve."
    )
    source_type_filter: Optional[str] = Field(
        None,
        description="Optionally filter by source type: 'faq', 'company_info', 'email_template', 'other'."
    )


class RAGQueryOutput(BaseModel):
    """Output from a RAG query."""

    query: str = Field(..., description="The original query.")
    chunks: List[RetrievedChunk] = Field(
        ..., description="Retrieved chunks ordered by similarity score descending."
    )
    context_text: str = Field(
        ...,
        description=(
            "Pre-formatted context string ready to inject into a prompt. "
            "Concatenates all chunk texts with source labels."
        )
    )
    total_found: int = Field(..., description="Total number of chunks found above threshold.")


# EMBEDDING — LOCAL vs PRODUCTION

_local_model = None

def _get_local_model():
    """Load all-MiniLM-L6-v2 locally via sentence-transformers. Cached."""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[RAG] Loading all-MiniLM-L6-v2 from HuggingFace Hub...")
        _local_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("[RAG] Model loaded.")
    return _local_model


def _embed_local(texts: List[str]) -> List[List[float]]:
    """
    Embed texts using all-MiniLM-L6-v2 locally.
    Falls back to a deterministic TF-IDF style embedding if the model
    cannot be downloaded (e.g. sandbox/offline environment).
    On your machine with internet access, the HuggingFace model will load normally.
    """
    try:
        model = _get_local_model()
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()
    except Exception as e:
        logger.warning(
            f"[RAG] sentence-transformers unavailable ({e.__class__.__name__}: {str(e)[:60]}). "
            f"Using fallback hash embedding. Install sentence-transformers and ensure "
            f"internet access for full embedding quality."
        )
        return _embed_fallback(texts)


def _embed_fallback(texts: List[str]) -> List[List[float]]:
    """
    Deterministic fallback embedding using character n-gram hashing.
    Produces 384-dimensional vectors to match all-MiniLM-L6-v2 output dimensions.
    Quality is lower than the real model but sufficient for development/testing.
    Used ONLY when the real model cannot be loaded.
    """
    import hashlib

    dim = 384

    def text_to_vec(text: str) -> List[float]:
        text = text.lower()
        vec = [0.0] * dim

        # Character trigrams
        for i in range(len(text) - 2):
            trigram = text[i:i+3]
            h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0

        # Word unigrams
        for word in text.split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 2.0

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    return [text_to_vec(t) for t in texts]


def _embed_sagemaker(texts: List[str]) -> List[List[float]]:
    """
    Embed texts via SageMaker endpoint.
    The endpoint must be deployed with all-MiniLM-L6-v2.
    """
    import boto3
    import json

    client = boto3.client("sagemaker-runtime", region_name=SAGEMAKER_REGION)
    embeddings = []

    # Batch in groups of 32 to avoid payload limits
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = json.dumps({"inputs": batch})
        response = client.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT,
            ContentType="application/json",
            Body=payload,
        )
        result = json.loads(response["Body"].read())
        embeddings.extend(result)

    return embeddings


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed texts using the appropriate backend for the current environment.
    Local → sentence-transformers
    Production → SageMaker
    """
    if settings.is_production() and SAGEMAKER_ENDPOINT:
        return _embed_sagemaker(texts)
    return _embed_local(texts)


# VECTOR SIMILARITY — LOCAL

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# CHUNKING

def _chunk_text(text: str) -> List[str]:
    """
    Split text into overlapping chunks for embedding.
    Strategy: paragraph-aware sliding window.
    """
    # Normalize whitespace
    text = text.strip()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If adding this paragraph would exceed chunk size, flush and start new chunk
        if len(current_chunk) + len(para) > CHUNK_SIZE_CHARS and current_chunk:
            chunks.append(current_chunk.strip())
            # Keep last CHUNK_OVERLAP_CHARS as overlap
            overlap_start = max(0, len(current_chunk) - CHUNK_OVERLAP_CHARS)
            current_chunk = current_chunk[overlap_start:] + "\n\n" + para
        else:
            current_chunk = (current_chunk + "\n\n" + para).strip() if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # If a single paragraph is too long, split it by sentences
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= CHUNK_SIZE_CHARS:
            final_chunks.append(chunk)
        else:
            # Split by sentence
            sentences = chunk.replace(". ", ".|").split("|")
            sub_chunk = ""
            for sent in sentences:
                if len(sub_chunk) + len(sent) > CHUNK_SIZE_CHARS and sub_chunk:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = sent
                else:
                    sub_chunk = (sub_chunk + " " + sent).strip()
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())

    return final_chunks if final_chunks else [text[:CHUNK_SIZE_CHARS]]


# LOCAL VECTOR STORE (SQLite)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalRAGStore:
    """
    SQLite-backed vector store for local development.
    Embeddings stored as JSON arrays.
    Cosine similarity computed in Python.
    """

    def __init__(self):
        self.db = get_db()

    def ingest(self, inp: IngestDocumentInput) -> IngestDocumentOutput:
        """Chunk, embed, and store a document."""
        now = _now_iso()
        doc_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row

        # Save document record
        conn.execute(
            """INSERT INTO rag_documents
               (id, user_id, title, source_type, raw_content, chunk_count,
                file_size_bytes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (doc_id, inp.user_id, inp.title, inp.source_type,
             inp.raw_content, 0, inp.file_size_bytes, now, now)
        )

        # Chunk the content
        chunks = _chunk_text(inp.raw_content)
        logger.info(f"[RAG] Document '{inp.title}' split into {len(chunks)} chunks")

        # Embed all chunks in one batch
        embeddings = embed_texts(chunks)

        # Store chunks with embeddings
        for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO rag_chunks
                   (id, document_id, user_id, chunk_index, chunk_text,
                    embedding, token_count, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (chunk_id, doc_id, inp.user_id, i, chunk_text,
                 json.dumps(embedding), len(chunk_text.split()), now)
            )

        # Update chunk count
        conn.execute(
            "UPDATE rag_documents SET chunk_count = ?, embedded_at = ?, updated_at = ? WHERE id = ?",
            (len(chunks), now, now, doc_id)
        )
        conn.commit()
        conn.close()

        logger.info(
            f"[RAG] Ingested document '{inp.title}' — {len(chunks)} chunks stored "
            f"(doc_id={doc_id[:8]}...)"
        )

        return IngestDocumentOutput(
            document_id=doc_id,
            chunk_count=len(chunks),
            title=inp.title,
            source_type=inp.source_type,
        )

    def query(self, inp: RAGQueryInput) -> RAGQueryOutput:
        """Query the vector store via cosine similarity."""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row

        # Build query for chunks
        if inp.source_type_filter:
            rows = conn.execute(
                """SELECT rc.id, rc.document_id, rc.chunk_text, rc.embedding,
                          rd.title, rd.source_type
                   FROM rag_chunks rc
                   JOIN rag_documents rd ON rc.document_id = rd.id
                   WHERE rc.user_id = ? AND rd.source_type = ?""",
                (inp.user_id, inp.source_type_filter)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT rc.id, rc.document_id, rc.chunk_text, rc.embedding,
                          rd.title, rd.source_type
                   FROM rag_chunks rc
                   JOIN rag_documents rd ON rc.document_id = rd.id
                   WHERE rc.user_id = ?""",
                (inp.user_id,)
            ).fetchall()

        conn.close()

        if not rows:
            return RAGQueryOutput(
                query=inp.query,
                chunks=[],
                context_text="No relevant documents found in the knowledge base.",
                total_found=0,
            )

        # Embed the query
        query_embedding = embed_texts([inp.query])[0]

        # Score all chunks
        scored: List[Tuple[float, dict]] = []
        for row in rows:
            r = dict(row)
            try:
                chunk_embedding = json.loads(r["embedding"])
                score = _cosine_similarity(query_embedding, chunk_embedding)
                if score >= MIN_SIMILARITY:
                    scored.append((score, r))
            except Exception as e:
                logger.warning(f"[RAG] Failed to score chunk {r['id'][:8]}: {e}")

        # Sort by score descending, take top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:inp.top_k]

        retrieved = [
            RetrievedChunk(
                chunk_id=r["id"],
                document_id=r["document_id"],
                document_title=r["title"],
                source_type=r["source_type"],
                chunk_text=r["chunk_text"],
                similarity_score=round(score, 4),
            )
            for score, r in top
        ]

        # Build context string for prompt injection
        context_parts = []
        for chunk in retrieved:
            context_parts.append(
                f"[{chunk.source_type.upper()} — {chunk.document_title}]\n{chunk.chunk_text}"
            )
        context_text = "\n\n---\n\n".join(context_parts) if context_parts else \
            "No relevant context found."

        logger.info(
            f"[RAG] Query '{inp.query[:50]}...' → {len(retrieved)} chunks retrieved "
            f"(top score: {retrieved[0].similarity_score if retrieved else 0:.2f})"
        )

        return RAGQueryOutput(
            query=inp.query,
            chunks=retrieved,
            context_text=context_text,
            total_found=len(retrieved),
        )

    def delete_document(self, document_id: str, user_id: str) -> bool:
        """Delete a document and all its chunks."""
        conn = sqlite3.connect(self.db.db_path)
        # Verify ownership
        row = conn.execute(
            "SELECT id FROM rag_documents WHERE id = ? AND user_id = ?",
            (document_id, user_id)
        ).fetchone()
        if not row:
            conn.close()
            return False
        conn.execute("DELETE FROM rag_chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM rag_documents WHERE id = ?", (document_id,))
        conn.commit()
        conn.close()
        logger.info(f"[RAG] Deleted document {document_id[:8]} and all chunks")
        return True

    def list_documents(self, user_id: str) -> List[dict]:
        """List all documents for a user."""
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, title, source_type, chunk_count, file_size_bytes,
                      embedded_at, created_at, updated_at
               FROM rag_documents WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# PRODUCTION VECTOR STORE (S3 Vectors stub)

class ProductionRAGStore:
    """
    S3 Vectors + SageMaker-backed store for production.
    Implement when deploying to AWS.
    """

    def ingest(self, inp: IngestDocumentInput) -> IngestDocumentOutput:
        raise NotImplementedError(
            "Production RAG store not yet implemented. "
            "Set SDA_ENV=local for development."
        )

    def query(self, inp: RAGQueryInput) -> RAGQueryOutput:
        raise NotImplementedError("Production RAG store not yet implemented.")

    def delete_document(self, document_id: str, user_id: str) -> bool:
        raise NotImplementedError("Production RAG store not yet implemented.")

    def list_documents(self, user_id: str) -> List[dict]:
        raise NotImplementedError("Production RAG store not yet implemented.")


# FACTORY

_rag_store = None

def get_rag_store():
    """Return the appropriate RAG store for the current environment."""
    global _rag_store
    if _rag_store is None:
        if settings.is_production():
            _rag_store = ProductionRAGStore()
        else:
            _rag_store = LocalRAGStore()
    return _rag_store


# TEST MAIN

if __name__ == "__main__":
    import os
    os.environ.setdefault("SDA_ENV", "local")
    logging.basicConfig(level=logging.INFO)

    store = get_rag_store()

    # Ingest a test document
    result = store.ingest(IngestDocumentInput(
        user_id="test-user-001",
        title="Andela FAQ",
        source_type="faq",
        raw_content="""
What is Andela?
Andela connects companies with pre-vetted senior software engineers from emerging markets.
We specialise in AI, ML, backend engineering, and data science.

How fast can you get an engineer started?
Typical onboarding time is 5 to 7 business days from contract signing.
For urgent roles, we can sometimes move faster.

What does it cost?
Pricing starts at $5,000 per month per engineer for senior-level talent.
Volume discounts are available for teams of 5 or more.

Do engineers work in our timezone?
Yes. All Andela engineers work in your timezone. Overlap is guaranteed.

What if the engineer is not a good fit?
We offer a 2-week trial period. If it is not working, we replace the engineer at no extra cost.

How does vetting work?
Every Andela engineer goes through a rigorous 4-stage technical assessment including
coding challenges, system design interviews, and soft skills evaluation.
Only the top 1% of applicants are accepted onto the platform.
        """,
    ))
    print(f"\n✅ Ingested: {result.document_id[:8]}... — {result.chunk_count} chunks")

    # Query it
    query_result = store.query(RAGQueryInput(
        query="How quickly can we start and what is the pricing?",
        user_id="test-user-001",
        top_k=3,
    ))
    print(f"\n🔍 Query results: {query_result.total_found} chunks")
    for chunk in query_result.chunks:
        print(f"  [{chunk.similarity_score:.2f}] {chunk.chunk_text[:80]}...")

    print(f"\n📝 Context for prompt:\n{query_result.context_text[:300]}...")
