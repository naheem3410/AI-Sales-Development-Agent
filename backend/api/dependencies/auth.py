"""
auth.py
-------
Clerk JWT authentication dependency.

How it works:
  1. Frontend sends: Authorization: Bearer <clerk_session_token>
  2. FastAPI extracts the token via HTTPBearer
  3. We verify the JWT against Clerk's JWKS endpoint (networkless with cached public key)
  4. We extract the clerk_user_id from the `sub` claim and email/name from session claims
     (Option A: add `email` and name fields to the Session token in the Clerk Dashboard JWT template.)
  5. We look up the user in our own database
  6. If user does not exist locally (first request after webhook delay), we create them
  7. We return the local user dict — available in every route via Depends(get_current_user)

Local dev:
  Set CLERK_DEV_MODE=true and CLERK_DEV_USER_ID to bypass JWT verification entirely.
  This lets you test routes without a real Clerk token.

Production:
  Set CLERK_JWKS_URL and CLERK_SECRET_KEY in environment.
  JWT verification is done networklessly using the cached public key.
"""

import os
import logging
from typing import Optional, Dict, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.infrastructure.factory import get_db

logger = logging.getLogger(__name__)

# ── Config

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_DEV_MODE = os.getenv("CLERK_DEV_MODE", "false").lower() == "true"
CLERK_DEV_USER_ID = os.getenv("CLERK_DEV_USER_ID", "dev_user_001")
CLERK_DEV_EMAIL = os.getenv("CLERK_DEV_EMAIL", "dev@sda-local.dev")


def _csv_lower_set(env_key: str, default: str) -> frozenset:
    """Comma-separated env list → lowercase frozenset for comparisons."""
    raw = os.getenv(env_key, default)
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())


# CommercePlan.slug / CommercePlan.name values that do not count as a paid subscription
CLERK_UNPAID_PLAN_SLUGS = _csv_lower_set(
    "CLERK_UNPAID_PLAN_SLUGS",
    "free_user,free",
)
CLERK_UNPAID_PLAN_NAMES = _csv_lower_set(
    "CLERK_UNPAID_PLAN_NAMES",
    "free",
)


def clerk_subscription_grants_access(subscription: Dict[str, Any]) -> bool:
    """
    True if Clerk's CommerceSubscription should unlock paid routes and /users/me flag.

    Requires top-level ``status`` of ``active`` or ``trialing``, then inspects
    ``subscriptionItems[].plan`` (slug / name). Plans listed in
    ``CLERK_UNPAID_PLAN_SLUGS`` or ``CLERK_UNPAID_PLAN_NAMES`` are treated as unpaid.

    If there are no subscription items, only top-level ``status`` is used (backward compatible).
    """
    status = subscription.get("status")
    if status not in ("active", "trialing"):
        return False

    if not (
        subscription.get("subscriptionItems")
        or subscription.get("subscription_items")
        or []
    ):
        return True

    return not _subscription_has_unpaid_plan(subscription)


def _subscription_has_unpaid_plan(subscription: Dict[str, Any]) -> bool:
    """True if an active/trialing line item uses a plan slug/name in the unpaid lists."""
    raw_items = (
        subscription.get("subscriptionItems")
        or subscription.get("subscription_items")
        or []
    )
    if not raw_items:
        return False
    for item in raw_items:
        item_status = item.get("status")
        if item_status is not None and item_status not in ("active", "trialing"):
            continue
        plan = item.get("plan")
        if not isinstance(plan, dict):
            continue
        slug = (plan.get("slug") or "").strip().lower()
        name = (plan.get("name") or "").strip().lower()
        if slug in CLERK_UNPAID_PLAN_SLUGS or name in CLERK_UNPAID_PLAN_NAMES:
            return True
    return False


# Cache JWKS in memory — refreshed if verification fails
_jwks_cache: Optional[Dict] = None

http_bearer = HTTPBearer(auto_error=False)


def _primary_email_from_clerk_session(payload: Dict[str, Any]) -> str:
    """
    Read primary email from Clerk session JWT claims (Dashboard session token template).

    Supports common shapes when you map primary email into the token, plus OAuth-style claims.
    """
    for key in ("email", "primary_email_address"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    raw_list = payload.get("email_addresses")
    if isinstance(raw_list, list) and raw_list:
        first = raw_list[0]
        if isinstance(first, dict):
            nested = first.get("email_address") or first.get("email")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        elif isinstance(first, str) and first.strip():
            return first.strip()

    return ""


def _full_name_from_clerk_session(payload: Dict[str, Any]) -> Optional[str]:
    """
    Display name from Clerk session JWT (add first/last or full name via Dashboard session template).

    Tries separate first + last claims, then single-name claims OAuth/Clerk may emit.
    """
    fn = payload.get("first_name") or payload.get("given_name") or ""
    ln = payload.get("last_name") or payload.get("family_name") or ""
    combined = f"{fn} {ln}".strip()
    if combined:
        return combined
    for key in ("full_name", "name"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


# ── JWKS Fetcher

async def _get_jwks() -> Dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    if not CLERK_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured."
        )
    async with httpx.AsyncClient() as client:
        resp = await client.get(CLERK_JWKS_URL, timeout=10.0)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        logger.info("[Auth] JWKS fetched and cached.")
        return _jwks_cache


# ── JWT Verifier

async def _verify_clerk_token(token: str) -> Dict[str, Any]:
    """
    Verify a Clerk JWT token.
    Returns the decoded payload if valid.
    Raises HTTPException 401 if invalid.
    """
    try:
        import jwt as pyjwt
        from jwt import PyJWKClient

        jwks_client = PyJWKClient(CLERK_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
        return payload

    except Exception as e:
        logger.warning(f"[Auth] JWT verification failed: {e}")
        # Invalidate JWKS cache so it refreshes on next attempt
        global _jwks_cache
        _jwks_cache = None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── User Sync

def _get_or_create_user(clerk_user_id: str, email: str, full_name: Optional[str]) -> Dict:
    """
    Get user from local DB by Clerk user ID.
    If not found (webhook hasn't fired yet), create them now.
    The Clerk user_id is stored as the user's id in our DB.
    """
    db = get_db()

    # Try to fetch existing user
    user = db.get_user(clerk_user_id)
    if user:
        return user

    # User doesn't exist yet — create them
    # This handles the race condition where the webhook hasn't fired
    logger.info(f"[Auth] User {clerk_user_id} not in DB — creating on first request.")
    user = db.create_user_with_id(
        user_id=clerk_user_id,
        email=email,
        full_name=full_name,
    )
    return user


# ── Main Dependency

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> Dict:
    """
    FastAPI dependency. Inject into any route with: user = Depends(get_current_user)
    Returns the authenticated user dict from the local database.

    In dev mode (CLERK_DEV_MODE=true): bypasses JWT verification.
    In production: verifies Clerk JWT and syncs user to local DB.
    """

    # ── Dev mode bypass 
    if CLERK_DEV_MODE:
        logger.debug(f"[Auth] Dev mode — using hardcoded user {CLERK_DEV_USER_ID}")
        db = get_db()
        user = db.get_user(CLERK_DEV_USER_ID)
        if not user:
            user = db.create_user_with_id(
                user_id=CLERK_DEV_USER_ID,
                email=CLERK_DEV_EMAIL,
                full_name="Dev User",
            )
        return user

    # ── Require Bearer token 
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # ── Verify JWT 
    payload = await _verify_clerk_token(token)

    clerk_user_id = payload.get("sub")
    email = _primary_email_from_clerk_session(payload)
    full_name = _full_name_from_clerk_session(payload)

    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier.",
        )

    # ── Get or create user in local DB 
    try:
        user = _get_or_create_user(clerk_user_id, email, full_name)
    except RuntimeError as e:
        logger.error(f"[Auth] User sync failed for {clerk_user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not sync user account. Please try again.",
        )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load user account.",
        )
    return user


# ── Billing Guard 

async def require_active_subscription(
    user: Dict = Depends(get_current_user),
) -> Dict:
    """
    Dependency that enforces an active subscription.
    Gates all pipeline operations — campaign creation, pipeline runs.

    In dev mode: always passes.
    In production: checks Clerk Backend API for active subscription.
    """
    if CLERK_DEV_MODE:
        return user

    if not CLERK_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_SECRET_KEY not configured."
        )

    clerk_user_id = user["id"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}/billing/subscription",
                headers={
                    "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

            if resp.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="No active subscription. Please subscribe to access this feature.",
                )

            resp.raise_for_status()
            subscription = resp.json()

            if not clerk_subscription_grants_access(subscription):
                sub_status = subscription.get("status")
                if sub_status not in ("active", "trialing"):
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=(
                            f"Subscription is not active (status: {sub_status!r}). "
                            "Please subscribe or renew to access this feature."
                        ),
                    )
                if _subscription_has_unpaid_plan(subscription):
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=(
                            "This feature requires a paid plan. "
                            "Upgrade from your current free plan to continue."
                        ),
                    )
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="A paid subscription is required to access this feature.",
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Auth] Billing check failed for {clerk_user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify subscription. Please try again.",
        )

    return user


# ── Campaign Ownership Guard 

def verify_campaign_ownership(campaign: Optional[Dict], user: Dict, campaign_id: str):
    """
    Utility — call inside route handlers to verify the campaign belongs to the user.
    Raises 404 if not found, 403 if owned by someone else.
    """
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign {campaign_id} not found.",
        )
    if campaign["user_id"] != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this campaign.",
        )
