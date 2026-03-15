"""
Outbound webhook dispatcher — WizzardChat Routines engine.

Public API
----------
    from app.services.event_dispatcher import dispatch

    await dispatch("conversation.closed", event_payload, db)

``dispatch()`` is non-blocking: it writes WebhookDelivery rows to the DB and
schedules the HTTP delivery as an asyncio background task.  It never raises;
failures are recorded in WebhookDelivery and retried by the retry loop.

Retry policy (exponential back-off, all delays in seconds):
    attempt 1 → immediate
    attempt 2 → 30 s
    attempt 3 → 300 s (5 min)
    attempt 4 → 1800 s (30 min) — then abandoned
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import WebhookDelivery, WebhookSubscription

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSRF deny-list — block requests to private / loopback / link-local ranges
# ---------------------------------------------------------------------------
_BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_RETRY_DELAYS = [0, 30, 300, 1800]  # seconds before each attempt (index = attempt number)


def _is_ssrf_target(url: str) -> bool:
    """Return True if the URL resolves to a private/loopback address."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        addr = ipaddress.ip_address(socket.gethostbyname(host))
        return any(addr in net for net in _BLOCKED_NETS)
    except Exception:
        return False  # unresolvable → let httpx handle it (will fail cleanly)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

def _get_path(obj: Any, path: str) -> Any:
    """Safely walk a nested dict using dot-notation.  Returns None for missing paths."""
    parts = path.split(".")
    cur = obj
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _eval_condition(node: dict, event: dict) -> bool:
    """Recursively evaluate a condition tree against the event dict."""
    op = node.get("op", "").lower()

    if op in ("and", "all"):
        return all(_eval_condition(c, event) for c in node.get("conditions", []))
    if op in ("or", "any"):
        return any(_eval_condition(c, event) for c in node.get("conditions", []))

    field = node.get("field", "")
    value = _get_path(event, field)
    target = node.get("value")

    if op == "eq":        return value == target
    if op == "neq":       return value != target
    if op == "gt":        return value is not None and value > target
    if op == "lt":        return value is not None and value < target
    if op == "gte":       return value is not None and value >= target
    if op == "lte":       return value is not None and value <= target
    if op == "in":        return value in (target or [])
    if op == "not_in":    return value not in (target or [])
    if op == "contains":  return target in str(value or "")
    if op == "starts_with": return str(value or "").startswith(str(target or ""))
    if op == "is_null":   return value is None
    if op == "is_not_null": return value is not None

    _log.warning("event_dispatcher: unknown condition op '%s'", op)
    return True  # unknown op — pass through


# ---------------------------------------------------------------------------
# Payload template resolver
# ---------------------------------------------------------------------------

def _resolve_template(template: Any, event: dict) -> Any:
    """Replace ``${path}`` tokens in all string values of a nested dict/list."""
    if isinstance(template, str):
        # Replace every ${...} token
        import re
        def _replace(m: re.Match) -> str:
            val = _get_path(event, m.group(1))
            if val is None:
                return ""
            if isinstance(val, (dict, list)):
                return json.dumps(val, default=str)
            return str(val)
        return re.sub(r"\$\{([^}]+)\}", _replace, template)
    if isinstance(template, dict):
        return {k: _resolve_template(v, event) for k, v in template.items()}
    if isinstance(template, list):
        return [_resolve_template(i, event) for i in template]
    return template


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------

def _sign_payload(payload: dict, secret: str, timestamp: int) -> str:
    """Return HMAC-SHA256 hex digest over ``{timestamp}.{json_payload}``."""
    body = f"{timestamp}.{json.dumps(payload, separators=(',', ':'), sort_keys=True)}"
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _build_signature_header(payload: dict, secret: str) -> str:
    """Return value for ``X-Wizzard-Signature-256`` header."""
    ts = int(time.time())
    sig = _sign_payload(payload, secret, ts)
    return f"t={ts},v1={sig}"


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

async def dispatch(topic: str, event_data: dict, db: AsyncSession) -> None:
    """
    Fire an event to all matching, enabled WebhookSubscriptions.

    Creates WebhookDelivery rows and schedules delivery tasks.
    Always returns immediately; never raises.
    """
    try:
        result = await db.execute(
            select(WebhookSubscription).where(WebhookSubscription.enabled.is_(True))
        )
        subscriptions = result.scalars().all()

        event_id = str(uuid.uuid4())

        for sub in subscriptions:
            topics = sub.event_topics or []
            if topic not in topics:
                continue

            # Evaluate optional condition filter
            if sub.filter_expr:
                try:
                    if not _eval_condition(sub.filter_expr, event_data):
                        continue
                except Exception as exc:
                    _log.warning("Condition eval error sub=%s: %s", sub.id, exc)
                    continue

            # Resolve payload
            if sub.payload_template:
                try:
                    payload = _resolve_template(sub.payload_template, event_data)
                except Exception as exc:
                    _log.warning("Template resolve error sub=%s: %s", sub.id, exc)
                    payload = event_data
            else:
                payload = event_data

            delivery = WebhookDelivery(
                subscription_id=sub.id,
                event_id=event_id,
                event_topic=topic,
                payload=payload,
                status="queued",
                max_attempts=sub.retry_max,
                queued_at=datetime.utcnow(),
            )
            db.add(delivery)
            await db.flush()
            delivery_id = str(delivery.id)

            asyncio.create_task(_deliver(delivery_id))

    except Exception as exc:
        _log.error("dispatch error topic=%s: %s", topic, exc, exc_info=True)


# ---------------------------------------------------------------------------
# HTTP delivery (background task)
# ---------------------------------------------------------------------------

async def _deliver(delivery_id: str) -> None:
    """Attempt HTTP delivery.  Retries with exponential back-off."""
    async with async_session() as db:
        result = await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == uuid.UUID(delivery_id))
        )
        delivery = result.scalar_one_or_none()
        if not delivery or delivery.status in ("delivered", "abandoned"):
            return

        result2 = await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == delivery.subscription_id
            )
        )
        sub = result2.scalar_one_or_none()
        if not sub:
            delivery.status = "abandoned"
            await db.commit()
            return

        # Determine delay for this attempt
        attempt_index = delivery.attempts  # 0-based
        delay = _RETRY_DELAYS[min(attempt_index, len(_RETRY_DELAYS) - 1)]
        if delay > 0 and delivery.attempts > 0:
            await asyncio.sleep(delay)

    # Attempt the HTTP call
    await _attempt_http(delivery_id)


async def _attempt_http(delivery_id: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == uuid.UUID(delivery_id))
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return

        result2 = await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == delivery.subscription_id
            )
        )
        sub = result2.scalar_one_or_none()
        if not sub or not sub.enabled:
            delivery.status = "abandoned"
            await db.commit()
            return

        # SSRF guard
        if _is_ssrf_target(sub.url):
            _log.warning("SSRF blocked: delivery %s targeting %s", delivery_id, sub.url)
            delivery.status = "abandoned"
            delivery.response_body = "SSRF_BLOCKED"
            await db.commit()
            return

        headers = dict(sub.custom_headers or {})
        headers["Content-Type"] = "application/json"
        headers["X-Wizzard-Event"] = delivery.event_topic or ""
        headers["X-Wizzard-Delivery"] = delivery_id

        if sub.secret:
            headers["X-Wizzard-Signature-256"] = _build_signature_header(
                delivery.payload or {}, sub.secret
            )

        delivery.status = "dispatching"
        delivery.attempts = (delivery.attempts or 0) + 1
        delivery.last_attempt_at = datetime.utcnow()
        await db.commit()

        start_ms = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=sub.timeout_seconds or 10) as client:
                method = (sub.http_method or "POST").upper()
                if method == "GET":
                    resp = await client.get(sub.url, headers=headers)
                else:
                    resp = await client.post(
                        sub.url,
                        content=json.dumps(delivery.payload or {}, default=str),
                        headers=headers,
                    )
            duration = int((time.monotonic() - start_ms) * 1000)

            async with async_session() as db2:
                r2 = await db2.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.id == uuid.UUID(delivery_id)
                    )
                )
                d2 = r2.scalar_one_or_none()
                if not d2:
                    return
                d2.response_code = resp.status_code
                d2.response_body = resp.text[:2000]
                d2.duration_ms = duration

                if resp.is_success:
                    d2.status = "delivered"
                    d2.delivered_at = datetime.utcnow()
                    _log.info(
                        "Webhook delivered: sub=%s topic=%s status=%s",
                        d2.subscription_id, d2.event_topic, resp.status_code,
                    )
                else:
                    await _schedule_retry(d2)

                await db2.commit()

        except Exception as exc:
            duration = int((time.monotonic() - start_ms) * 1000)
            _log.warning("Webhook delivery error %s: %s", delivery_id, exc)

            async with async_session() as db3:
                r3 = await db3.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.id == uuid.UUID(delivery_id)
                    )
                )
                d3 = r3.scalar_one_or_none()
                if not d3:
                    return
                d3.response_body = str(exc)[:2000]
                d3.duration_ms = duration
                await _schedule_retry(d3)
                await db3.commit()


async def _schedule_retry(delivery: WebhookDelivery) -> None:
    """Mark delivery for retry or abandon if max attempts reached."""
    if delivery.attempts >= delivery.max_attempts:
        delivery.status = "abandoned"
        _log.warning(
            "Webhook abandoned after %d attempts: sub=%s topic=%s",
            delivery.attempts, delivery.subscription_id, delivery.event_topic,
        )
        return

    delay = _RETRY_DELAYS[min(delivery.attempts, len(_RETRY_DELAYS) - 1)]
    delivery.status = "failed"
    delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
    # Schedule background retry
    asyncio.create_task(_retry_after(str(delivery.id), delay))


async def _retry_after(delivery_id: str, delay_seconds: int) -> None:
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    await _attempt_http(delivery_id)


# ---------------------------------------------------------------------------
# Startup: re-queue any deliveries that were left in-flight at last shutdown
# ---------------------------------------------------------------------------

async def requeue_pending_deliveries() -> None:
    """Called once at startup.  Reschedules failed/queued deliveries."""
    async with async_session() as db:
        result = await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.status.in_(["queued", "dispatching", "failed"])
            )
        )
        deliveries = result.scalars().all()
        for d in deliveries:
            if d.status == "dispatching":
                # Was in-flight at shutdown — treat as failed, will retry
                d.status = "failed"
            asyncio.create_task(_deliver(str(d.id)))

        if deliveries:
            await db.commit()
            _log.info("Requeued %d pending webhook deliveries on startup", len(deliveries))
