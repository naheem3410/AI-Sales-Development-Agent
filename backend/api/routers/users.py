"""
users.py
--------
User profile endpoint.
Returns the current authenticated user's profile and subscription status.
"""

import os
import logging
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies.auth import clerk_subscription_grants_access, get_current_user
from backend.api.schemas.responses import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_DEV_MODE = os.getenv("CLERK_DEV_MODE", "false").lower() == "true"


async def _check_subscription(clerk_user_id: str) -> bool:
    """Check if user has an active subscription via Clerk Backend API."""
    if CLERK_DEV_MODE:
        return True

    if not CLERK_SECRET_KEY:
        return False

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}/billing/subscription",
                headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
                timeout=10.0,
            )
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            sub = resp.json()
            return clerk_subscription_grants_access(sub)
    except Exception as e:
        logger.warning(f"[Users] Subscription check failed for {clerk_user_id}: {e}")
        return False


@router.get("/me", response_model=UserResponse)
async def get_me(user: Dict = Depends(get_current_user)):
    """
    Returns the current authenticated user's profile and subscription status.
    Called by the frontend on load to determine plan access.
    """
    has_sub = await _check_subscription(user["id"])

    return UserResponse(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        plan=user.get("plan", "paid"),
        has_active_subscription=has_sub,
        created_at=user.get("created_at", ""),
    )
