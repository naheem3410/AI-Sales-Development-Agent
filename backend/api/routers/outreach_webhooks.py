"""
outreach_webhooks.py
--------------------
Webhook handlers for Resend (inbound email + delivery events) and Cal.com (booking).

Inbound bodies:
  Resend webhooks omit full email content; after `email.received` we fetch the message via
  `Emails.Receiving.get_async` using the user's Resend API key (or `RESEND_API_KEY` fallback).

Resend events handled:
  email.received       → inbound reply from a lead → run reply handler
  email.bounced        → mark outreach_log as bounced, cancel follow-ups
  email.delivery_delayed → log warning, no action

Cal.com events handled:
  BOOKING_CREATED      → mark lead as Converted, save to meeting_tracking

Signature verification:
  Resend: resend.Webhooks.verify({ payload, headers: {id,timestamp,signature}, webhook_secret })
  Cal.com: uses HMAC-SHA256 with CAL_WEBHOOK_SECRET

Local dev:
  Set OUTREACH_WEBHOOK_VERIFY=false to skip signature verification.
"""

import os
import re
import hmac
import hashlib
import json
import logging
import sqlite3
import uuid
from html import unescape
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request, HTTPException, Header, status
from fastapi.responses import JSONResponse

from backend.infrastructure.factory import get_db
from backend.core.enums import LeadStatus
from backend.core.outreach.agents.reply_handler import (
    InboundReplyEvent,
    handle_inbound_reply,
    _match_lead_by_email,
    _match_lead_by_resend_id,
)
from backend.core.outreach.sender import _cancel_followups, _now_iso, get_outreach_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Outreach Webhooks"])

OUTREACH_WEBHOOK_VERIFY = os.getenv("OUTREACH_WEBHOOK_VERIFY", "true").lower() == "true"
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "")
# Optional: fetch inbound bodies via Receiving API when lead → user key cannot be resolved
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
CAL_WEBHOOK_SECRET = os.getenv("CAL_WEBHOOK_SECRET", "")



# RESEND WEBHOOK


def _normalize_resend_data(data: Any) -> Dict[str, Any]:
    """
    Resend may send `data` as a JSON object or (in some paths) as a JSON string.
    All handlers expect a dict with .get().
    """
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        s = data.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return parsed
            logger.warning("[Webhook] Resend `data` parsed to non-dict; ignoring.")
            return {}
        except json.JSONDecodeError:
            logger.warning("[Webhook] Resend `data` string is not valid JSON; ignoring.")
            return {}
    logger.warning("[Webhook] Resend `data` has unexpected type: %s", type(data).__name__)
    return {}


def _inbound_from_address(data: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    raw = data.get("from")
    if isinstance(raw, dict):
        return (raw.get("email") or "").strip(), raw.get("name")
    if isinstance(raw, str):
        return raw.strip(), None
    return "", None


def _inbound_to_email(data: Dict[str, Any]) -> str:
    to = data.get("to")
    if not to:
        return ""
    if isinstance(to, str):
        return to.strip()
    if isinstance(to, list) and to:
        first = to[0]
        if isinstance(first, dict):
            return (first.get("email") or "").strip()
        if isinstance(first, str):
            return first.strip()
    if isinstance(to, dict):
        return (to.get("email") or "").strip()
    return ""


def _inbound_body_text(data: Dict[str, Any]) -> str:
    t = data.get("text")
    if isinstance(t, str) and t:
        return t
    body = data.get("body")
    if isinstance(body, dict):
        return (body.get("text") or "") or ""
    if isinstance(body, str):
        return body
    return ""


def _inbound_body_html(data: Dict[str, Any]) -> Optional[str]:
    h = data.get("html")
    if isinstance(h, str) and h:
        return h
    body = data.get("body")
    if isinstance(body, dict):
        return body.get("html")
    return None


def _inbound_in_reply_to(data: Dict[str, Any]) -> Optional[str]:
    direct = data.get("in_reply_to")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    headers = data.get("headers")
    if isinstance(headers, dict):
        return (
            headers.get("in-reply-to")
            or headers.get("In-Reply-To")
            or headers.get("in_reply_to")
        )
    return None


def _html_to_plain(html: str) -> str:
    """Minimal HTML → plain text when Resend returns only html."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _resend_api_key_for_inbound(from_email: str, in_reply_to: Optional[str]) -> Optional[str]:
    """
    Resolve the Resend API key used to call Receiving API for inbound mail.
    Prefer the matched lead's user's stored key; fall back to RESEND_API_KEY env.
    """
    lead = None
    if in_reply_to:
        lead = _match_lead_by_resend_id(in_reply_to)
    if not lead and from_email:
        lead = _match_lead_by_email(from_email)
    if lead:
        uid = lead["user_id"]
        settings = get_outreach_settings(uid)
        if settings and settings.resend_api_key:
            return settings.resend_api_key.strip() or None
        conn = sqlite3.connect(get_db().db_path)
        try:
            row = conn.execute(
                "SELECT resend_api_key FROM user_outreach_settings WHERE user_id = ?",
                (uid,),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return str(row[0]).strip() or None
    if RESEND_API_KEY:
        return RESEND_API_KEY
    return None


async def _fetch_received_email(email_id: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve full inbound email (text/html) via Resend Receiving API."""
    import resend as resend_sdk

    resend_sdk.api_key = api_key
    received = await resend_sdk.Emails.Receiving.get_async(email_id)
    if received is None:
        return None
    if isinstance(received, dict):
        return received
    try:
        return dict(received)
    except Exception:
        return None


def _verify_resend_svix(payload: str, svix_id: str, svix_timestamp: str, svix_signature: str) -> None:
    """Verify Resend (Svix) webhook signature — matches resend SDK Webhooks.verify(options dict)."""
    if not OUTREACH_WEBHOOK_VERIFY:
        return
    if not RESEND_WEBHOOK_SECRET:
        raise HTTPException(500, "RESEND_WEBHOOK_SECRET not configured.")
    try:
        import resend as resend_sdk

        resend_sdk.Webhooks.verify(
            {
                "payload": payload,
                "headers": {
                    "id": svix_id,
                    "timestamp": svix_timestamp,
                    "signature": svix_signature,
                },
                "webhook_secret": RESEND_WEBHOOK_SECRET,
            }
        )
    except ValueError as e:
        logger.warning(f"[Webhook] Resend signature verification failed: {e}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Resend webhook signature.")
    except Exception as e:
        logger.warning(f"[Webhook] Resend signature verification failed: {e}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Resend webhook signature.")


def _handle_email_bounced(data: dict):
    """Mark outreach_log entry as bounced. Cancel follow-ups."""
    resend_message_id = data.get("email_id")
    if not resend_message_id:
        return

    db = get_db()
    now = _now_iso()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT * FROM outreach_log WHERE resend_message_id = ?",
        (resend_message_id,)
    ).fetchone()

    if not row:
        conn.close()
        logger.warning(f"[Webhook] Bounced email not found in outreach_log: {resend_message_id}")
        return

    r = dict(row)
    conn.execute(
        "UPDATE outreach_log SET status='bounced', bounced_at=?, updated_at=? WHERE id=?",
        (now, now, r["id"])
    )
    conn.commit()
    conn.close()

    # Cancel follow-ups and mark lead as bounced
    _cancel_followups(r["lead_id"], reason="bounced")
    db.update_lead_status(r["lead_id"], LeadStatus.INACTIVE)
    logger.info(f"[Webhook] Email bounced for lead {r['lead_id'][:8]} — follow-ups cancelled")


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
):
    """
    Resend webhook endpoint.
    Handles: email.received (inbound reply), email.bounced, email.delivery_delayed.
    Register in Resend dashboard: POST https://yourdomain.com/webhooks/resend
    """
    raw = await request.body()
    payload_str = raw.decode("utf-8")

    if OUTREACH_WEBHOOK_VERIFY and all([svix_id, svix_timestamp, svix_signature]):
        _verify_resend_svix(payload_str, svix_id, svix_timestamp, svix_signature)

    try:
        body = json.loads(payload_str) if payload_str.strip() else {}
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body.")

    event_type = body.get("type")
    data = _normalize_resend_data(body.get("data"))

    logger.info(f"[Webhook] Resend event: {event_type}")

    if event_type == "email.received":
        # Inbound reply from a lead — fetch full body via Receiving API (webhook has metadata only).
        try:
            from_addr, from_name = _inbound_from_address(data)
            in_reply_to = _inbound_in_reply_to(data)

            email_id_raw = (data.get("email_id") or data.get("id") or "").strip()

            body_text = _inbound_body_text(data)
            body_html = _inbound_body_html(data)
            subject = data.get("subject")

            api_key = _resend_api_key_for_inbound(from_addr, in_reply_to)
            inbound_id = email_id_raw or data.get("id") or str(uuid.uuid4())

            if email_id_raw and api_key:
                try:
                    fetched = await _fetch_received_email(email_id_raw, api_key)
                    if fetched:
                        inbound_id = str(fetched.get("id") or email_id_raw or inbound_id)
                        txt = (fetched.get("text") or "").strip()
                        html = fetched.get("html")
                        if txt:
                            body_text = txt
                        elif html:
                            body_text = _html_to_plain(html)
                        if html:
                            body_html = html
                        fs = fetched.get("subject")
                        if isinstance(fs, str) and fs.strip():
                            subject = fs
                        hdrs = fetched.get("headers") or {}
                        if isinstance(hdrs, dict) and not in_reply_to:
                            hi = hdrs.get("In-Reply-To") or hdrs.get("in-reply-to")
                            if isinstance(hi, str) and hi.strip():
                                in_reply_to = hi.strip()
                        logger.debug(
                            "[Webhook] Loaded inbound via Receiving API id=%s len(text)=%s",
                            inbound_id,
                            len(body_text or ""),
                        )
                except Exception as e:
                    logger.warning(
                        "[Webhook] Receiving API fetch failed for %s: %s",
                        email_id_raw,
                        e,
                    )
            elif email_id_raw and not api_key:
                logger.warning(
                    "[Webhook] No Resend API key — inbound body may be empty "
                    "(configure user outreach settings or RESEND_API_KEY)."
                )

            event = InboundReplyEvent(
                resend_inbound_id=str(inbound_id),
                from_email=from_addr,
                from_name=from_name,
                to_email=_inbound_to_email(data),
                subject=subject,
                body_text=body_text or "",
                body_html=body_html,
                in_reply_to=in_reply_to,
            )
            # Process asynchronously — return 200 immediately to Resend
            import asyncio

            asyncio.create_task(handle_inbound_reply(event))
        except Exception as e:
            logger.error(f"[Webhook] Failed to process inbound reply: {e}")

    elif event_type == "email.bounced":
        try:
            _handle_email_bounced(data)
        except Exception as e:
            logger.error(f"[Webhook] Bounce handler failed: {e}")

    elif event_type == "email.delivery_delayed":
        logger.warning(
            f"[Webhook] Email delivery delayed — "
            f"email_id={data.get('email_id')} to={data.get('to')}"
        )

    elif event_type == "email.sent":
        logger.debug(f"[Webhook] Email sent confirmation: {data.get('email_id')}")

    else:
        logger.info(f"[Webhook] Unhandled Resend event: {event_type}")

    return {"received": True, "event": event_type}



# CAL.COM WEBHOOK

def _verify_cal_signature(body: bytes, signature: str) -> bool:
    """Verify Cal.com webhook signature using HMAC-SHA256."""
    if not OUTREACH_WEBHOOK_VERIFY:
        return True
    if not CAL_WEBHOOK_SECRET:
        logger.warning("[Webhook] CAL_WEBHOOK_SECRET not set — skipping verification")
        return True
    expected = hmac.new(
        CAL_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _handle_booking_created(data: dict):
    """
    Cal.com booking created.
    Match to a lead by attendee email, mark as Converted, save to meeting_tracking.
    """
    attendee_email = None
    attendees = data.get("attendees", [])
    if attendees:
        attendee_email = attendees[0].get("email")
    if not attendee_email:
        attendee_email = data.get("attendee", {}).get("email")

    if not attendee_email:
        logger.warning("[Webhook] Cal.com booking has no attendee email")
        return

    db = get_db()
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row

    # Find lead by email
    lead = conn.execute(
        "SELECT * FROM leads WHERE email = ? ORDER BY updated_at DESC LIMIT 1",
        (attendee_email,)
    ).fetchone()

    if not lead:
        conn.close()
        logger.warning(f"[Webhook] Cal.com booking — no lead found for {attendee_email}")
        return

    lead = dict(lead)
    lead_id = lead["id"]
    campaign_id = lead["campaign_id"]
    user_id = lead["user_id"]
    now = _now_iso()

    # Save meeting record
    meeting_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO meeting_tracking
           (id, lead_id, campaign_id, user_id, cal_booking_uid,
            meeting_title, meeting_start_at, meeting_end_at,
            attendee_email, attendee_name, cal_event_type,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            meeting_id, lead_id, campaign_id, user_id,
            data.get("uid"),
            data.get("title"),
            data.get("startTime"),
            data.get("endTime"),
            attendee_email,
            attendees[0].get("name") if attendees else None,
            data.get("eventTypeId"),
            now, now,
        )
    )
    conn.commit()
    conn.close()

    # Mark lead as Converted
    db.update_lead_status(lead_id, LeadStatus.CONVERTED)
    # Cancel all pending follow-ups
    _cancel_followups(lead_id, reason="converted")

    logger.info(
        f"[Webhook] Cal.com booking confirmed — "
        f"lead {lead_id[:8]} ({attendee_email}) marked Converted"
    )


@router.post("/cal")
async def cal_webhook(
    request: Request,
    x_cal_signature_256: str = Header(None, alias="X-Cal-Signature-256"),
):
    """
    Cal.com webhook endpoint.
    Handles: BOOKING_CREATED.
    Register in Cal.com: POST https://yourdomain.com/webhooks/cal
    Events: booking_created
    """
    body_bytes = await request.body()

    if OUTREACH_WEBHOOK_VERIFY and x_cal_signature_256:
        if not _verify_cal_signature(body_bytes, x_cal_signature_256):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Cal.com signature.")

    try:
        body = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body.")

    event_type = body.get("triggerEvent")
    payload = body.get("payload", {})

    logger.info(f"[Webhook] Cal.com event: {event_type}")

    if event_type == "BOOKING_CREATED":
        try:
            _handle_booking_created(payload)
        except Exception as e:
            logger.error(f"[Webhook] Cal.com booking handler failed: {e}")
            return JSONResponse(
                status_code=200,
                content={"received": True, "error": str(e)}
            )
    else:
        logger.info(f"[Webhook] Unhandled Cal.com event: {event_type}")

    return {"received": True, "event": event_type}
