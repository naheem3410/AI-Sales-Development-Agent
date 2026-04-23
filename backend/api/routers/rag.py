"""
rag.py
------
RAG document management endpoints:
  POST   /rag/documents              upload and embed a document (JSON body)
  POST   /rag/documents/file         upload PDF / Word / text / markdown file
  GET    /rag/documents              list all documents for user
  DELETE /rag/documents/{doc_id}     remove a document and its chunks
  POST   /rag/query                  query the RAG store (for testing/admin)
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel, Field

from backend.api.dependencies.auth import get_current_user
from backend.core.outreach.rag.rag_store import (
    get_rag_store,
    IngestDocumentInput,
    RAGQueryInput, RAGQueryOutput,
)
from backend.core.outreach.rag.document_extract import (
    DocumentExtractError,
    default_title_from_filename,
    extract_text_from_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["RAG"])


# REQUEST / RESPONSE MODELS

class DocumentUploadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Document title.")
    source_type: str = Field(
        ...,
        description="Category: 'faq', 'company_info', 'email_template', 'other'."
    )
    content: str = Field(
        ..., min_length=10,
        description="Full text content of the document."
    )


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    source_type: str
    chunk_count: int


class DocumentListItem(BaseModel):
    id: str
    title: str
    source_type: str
    chunk_count: int
    file_size_bytes: Optional[int]
    embedded_at: Optional[str]
    created_at: str


class DocumentListResponse(BaseModel):
    documents: List[DocumentListItem]
    total: int


class RAGQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query to search for.")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve.")
    source_type_filter: Optional[str] = Field(
        None, description="Filter by source type."
    )


# ENDPOINTS

@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    body: DocumentUploadRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Upload a document to the RAG knowledge base.
    The document is chunked and embedded immediately.
    Available for reply agent to use when answering lead questions.

    source_type options:
      faq            — frequently asked questions
      company_info   — about the company, team, values
      email_template — proven outreach templates the agent can adapt
      other          — anything else
    """
    valid_types = {"faq", "company_info", "email_template", "other"}
    if body.source_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source_type must be one of: {', '.join(sorted(valid_types))}"
        )

    rag_store = get_rag_store()

    try:
        result = rag_store.ingest(IngestDocumentInput(
            user_id=user["id"],
            title=body.title,
            source_type=body.source_type,
            raw_content=body.content,
        ))
    except Exception as e:
        logger.error(f"[RAG] Document ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingestion failed: {str(e)}"
        )

    logger.info(
        f"[RAG] User {user['id'][:8]} ingested document "
        f"'{body.title}' — {result.chunk_count} chunks"
    )

    return DocumentResponse(
        document_id=result.document_id,
        title=result.title,
        source_type=result.source_type,
        chunk_count=result.chunk_count,
    )


@router.post(
    "/documents/file",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_file(
    file: UploadFile = File(..., description="PDF, .docx, .txt, .md, or .markdown"),
    source_type: str = Form(
        ...,
        description="Category: faq, company_info, email_template, other.",
    ),
    title: Optional[str] = Form(
        None,
        description="Optional title; defaults to the uploaded filename (without extension).",
    ),
    user: Dict = Depends(get_current_user),
):
    """
    Upload a file; text is extracted server-side, then chunked and embedded like POST /documents.

    **Supported types:** `.pdf`, `.docx`, `.txt`, `.md`, `.markdown`

    Legacy Word `.doc` is not supported (use `.docx`).
    """
    valid_types = {"faq", "company_info", "email_template", "other"}
    if source_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source_type must be one of: {', '.join(sorted(valid_types))}",
        )

    raw = await file.read()
    fname = file.filename or "upload"

    try:
        text = extract_text_from_upload(fname, raw)
    except DocumentExtractError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    if len(text) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Extracted text is too short (minimum 10 characters).",
        )

    display_title = (title or "").strip() or default_title_from_filename(fname)

    rag_store = get_rag_store()
    try:
        result = rag_store.ingest(
            IngestDocumentInput(
                user_id=user["id"],
                title=display_title[:200],
                source_type=source_type,
                raw_content=text,
                file_size_bytes=len(raw),
            )
        )
    except Exception as e:
        logger.error(f"[RAG] File ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingestion failed: {str(e)}",
        )

    logger.info(
        f"[RAG] User {user['id'][:8]} ingested file '{fname}' "
        f"as '{display_title}' — {result.chunk_count} chunks"
    )

    return DocumentResponse(
        document_id=result.document_id,
        title=result.title,
        source_type=result.source_type,
        chunk_count=result.chunk_count,
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(user: Dict = Depends(get_current_user)):
    """List all RAG documents uploaded by the current user."""
    rag_store = get_rag_store()
    docs = rag_store.list_documents(user["id"])

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=d["id"],
                title=d["title"],
                source_type=d["source_type"],
                chunk_count=d["chunk_count"],
                file_size_bytes=d.get("file_size_bytes"),
                embedded_at=d.get("embedded_at"),
                created_at=d["created_at"],
            )
            for d in docs
        ],
        total=len(docs),
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: str,
    user: Dict = Depends(get_current_user),
):
    """
    Delete a document and all its chunks from the RAG store.
    The reply agent will no longer have access to this document.
    """
    rag_store = get_rag_store()
    deleted = rag_store.delete_document(document_id, user["id"])

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found."
        )

    return {"message": f"Document {document_id} deleted.", "document_id": document_id}


@router.post("/query", response_model=RAGQueryOutput)
async def query_rag(
    body: RAGQueryRequest,
    user: Dict = Depends(get_current_user),
):
    """
    Query the RAG store directly.
    Admin/testing endpoint — lets you see what context the reply agent would retrieve
    for a given question.
    """
    rag_store = get_rag_store()

    result = rag_store.query(RAGQueryInput(
        query=body.query,
        user_id=user["id"],
        top_k=body.top_k,
        source_type_filter=body.source_type_filter,
    ))

    return result
