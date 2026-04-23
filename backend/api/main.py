"""
main.py
-------
FastAPI application entry point.

Local:
    uvicorn api.main:app --reload --port 8000

Production:
    Runs behind AWS API Gateway.
    Deployed as a container on ECS or Lambda via Mangum.

Environment:
    SDA_ENV=local      → SQLite + file queue
    SDA_ENV=production → Aurora + SQS
    CLERK_DEV_MODE=true → bypass JWT verification for local testing
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise infrastructure on startup."""
    logger.info(f"[SDA API] Starting up — environment: {settings.env.value}")

    # Trigger DB and queue initialisation (creates SQLite + dirs if local)
    from backend.infrastructure.factory import get_db, get_queue, get_storage
    get_db()
    get_queue()
    get_storage()

    logger.info("[SDA API] Infrastructure ready.")
    yield
    logger.info("[SDA API] Shutting down.")


# ── App 

app = FastAPI(
    title="SDA Platform API",
    description=(
        "AI Sales Development Agent — autonomous outbound sales pipeline. "
        "Researches prospects, writes personalised emails, manages campaigns."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global Exception Handler 

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[SDA API] Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error.", "detail": str(exc)},
    )


# ── Health Check 

@app.get("/health", tags=["Health"])
async def health():
    """
    Health check endpoint.
    Used by load balancers and monitoring.
    No authentication required.
    """
    return {
        "status": "healthy",
        "environment": settings.env.value,
        "version": "1.0.0",
    }


# ── Routers 

from backend.api.routers import webhooks, users, campaigns, pipeline, leads, emails, analytics, outreach, outreach_webhooks, rag

app.include_router(webhooks.router)
app.include_router(users.router)
app.include_router(campaigns.router)
app.include_router(pipeline.router)
app.include_router(leads.router)
app.include_router(emails.router)
app.include_router(analytics.router)
app.include_router(outreach.router)
app.include_router(outreach_webhooks.router)
app.include_router(rag.router)

logger.info("[SDA API] All routers registered.")
logger.info(f"[SDA API] CORS origins: {ALLOWED_ORIGINS}")
logger.info(f"[SDA API] Clerk dev mode: {os.getenv('CLERK_DEV_MODE', 'false')}")
