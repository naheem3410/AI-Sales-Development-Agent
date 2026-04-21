"""
webhooks.py
-----------
Clerk webhook endpoint.
Receives user lifecycle events from Clerk and syncs to local database.

Events handled:
  user.created  → create user in DB
  user.updated  → update user in DB
  user.deleted  → mark user deleted (soft delete — preserve campaign data)

Security:
  In production, verify the Svix webhook signature using CLERK_WEBHOOK_SECRET.
  In dev mode, signature verification is skipped.

Setup in Clerk dashboard:
  Endpoint URL: https://your-domain.com/webhooks/clerk
  Events: user.created, user.updated, user.deleted
"""

import os
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException, status, Header
from fastapi.responses import JSONResponse

from backend.infrastructure.factory import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET", "")
CLERK_DEV_MODE = os.getenv("CLERK_DEV_MODE", "false").lower() == "true"


# ── Signature Verification

async def _verify_webhook_signature(request: Request, svix_id: str, svix_timestamp: str, svix_signature: str):
    """
    Verify the webhook came from Clerk using Svix signature.
    Skip in dev mode.
    """
    if CLERK_DEV_MODE:
        return

    if not CLERK_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_WEBHOOK_SECRET not configured."
        )

    try:
        from svix.webhooks import Webhook
        body = await request.body()
        wh = Webhook(CLERK_WEBHOOK_SECRET)
        wh.verify(body, {
            "svix-id": svix_id,
            "svix-timestamp": svix_timestamp,
            "svix-signature": svix_signature,
        })
    except Exception as e:
        logger.warning(f"[Webhook] Signature verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature."
        )


# ── Event Handlers 

def _handle_user_created(data: Dict[str, Any]):
    """Sync new Clerk user to local database."""
    db = get_db()

    clerk_user_id = data.get("id")
    email_addresses = data.get("email_addresses", [])
    primary_email_id = data.get("primary_email_address_id")

    # Get primary email
    email = ""
    for addr in email_addresses:
        if addr.get("id") == primary_email_id:
            email = addr.get("email_address", "")
            break
    if not email and email_addresses:
        email = email_addresses[0].get("email_address", "")

    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip() or None

    # Check if already exists (idempotent)
    existing = db.get_user(clerk_user_id)
    if existing:
        logger.info(f"[Webhook] user.created — user {clerk_user_id} already exists, skipping.")
        return

    db.create_user_with_id(
        user_id=clerk_user_id,
        email=email,
        full_name=full_name,
    )
    logger.info(f"[Webhook] user.created — created user {clerk_user_id} <{email}>")


def _handle_user_updated(data: Dict[str, Any]):
    """Sync updated Clerk user data to local database."""
    db = get_db()

    clerk_user_id = data.get("id")
    existing = db.get_user(clerk_user_id)
    if not existing:
        # User doesn't exist — create them
        _handle_user_created(data)
        return

    email_addresses = data.get("email_addresses", [])
    primary_email_id = data.get("primary_email_address_id")
    email = existing["email"]
    for addr in email_addresses:
        if addr.get("id") == primary_email_id:
            email = addr.get("email_address", email)
            break

    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip() or existing.get("full_name")

    db.update_user(clerk_user_id, {
        "email": email,
        "full_name": full_name,
    })
    logger.info(f"[Webhook] user.updated — updated user {clerk_user_id}")


def _handle_user_deleted(data: Dict[str, Any]):
    """
    Soft delete — mark user as deleted but preserve all campaign data.
    We do not hard delete because campaigns and leads reference the user.
    """
    db = get_db()
    clerk_user_id = data.get("id")
    existing = db.get_user(clerk_user_id)
    if not existing:
        logger.info(f"[Webhook] user.deleted — user {clerk_user_id} not found, skipping.")
        return

    db.update_user(clerk_user_id, {
        "plan": "deleted",
        "email": f"deleted_{clerk_user_id}@deleted.sda",
    })
    logger.info(f"[Webhook] user.deleted — soft deleted user {clerk_user_id}")


# ── Webhook Endpoint

@router.post("/clerk", status_code=status.HTTP_200_OK)
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
):
    """
    Receives Clerk webhook events.
    Must be registered in the Clerk dashboard.
    Not called by the frontend.
    """
    # Verify signature
    if not CLERK_DEV_MODE:
        if not all([svix_id, svix_timestamp, svix_signature]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Svix signature headers."
            )
        await _verify_webhook_signature(request, svix_id, svix_timestamp, svix_signature)

    # Parse body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body."
        )

    event_type = body.get("type")
    data = body.get("data", {})

    logger.info(f"[Webhook] Received event: {event_type}")

    # Route to handler
    handlers = {
        "user.created": _handle_user_created,
        "user.updated": _handle_user_updated,
        "user.deleted": _handle_user_deleted,
    }

    handler = handlers.get(event_type)
    if handler:
        try:
            handler(data)
        except Exception as e:
            logger.error(f"[Webhook] Handler failed for {event_type}: {e}")
            # Return 200 anyway — Clerk will retry on non-2xx
            # We log the error but don't want infinite retries for bad data
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"received": True, "error": str(e)}
            )
    else:
        logger.info(f"[Webhook] Unhandled event type: {event_type} — ignoring.")

    return {"received": True, "event": event_type}
