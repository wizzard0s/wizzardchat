"""Email Connector router — IMAP/SMTP connector CRUD and inbound email routing.

Endpoints
---------
GET    /api/v1/email-connectors          — list all email connectors
POST   /api/v1/email-connectors          — create an email connector
GET    /api/v1/email-connectors/{id}     — get one email connector
PUT    /api/v1/email-connectors/{id}     — update an email connector
DELETE /api/v1/email-connectors/{id}     — delete an email connector
POST   /api/v1/email-connectors/{id}/test — test IMAP connectivity
POST   /api/v1/inbound/email             — process an inbound email (webhook or IMAP poll)

Background IMAP polling
-----------------------
When a connector is created or updated with ``is_active=True`` and valid IMAP
credentials, a background asyncio task polls the mailbox every
``poll_interval_seconds`` and routes new messages through the inbound handler.
The task is cancelled and restarted on update, and cancelled on delete.

Routing pre-condition
---------------------
To route email threads into a flow, a ``Connector`` record in the connectors
table with ``flow_id`` equal to the email connector's ``flow_id`` must exist.
``inbound_router._resolve_connector`` finds it automatically.  Create one
Connector per email flow in the Connectors UI.
"""

from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import imaplib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import async_session, get_db
from app.models import EmailConnector, FlowNode, Interaction
from app.schemas import (
    EmailConnectorCreate,
    EmailConnectorOut,
    EmailConnectorUpdate,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/email-connectors",
    tags=["email-connectors"],
    dependencies=[Depends(get_current_user)],
)

# Executor for blocking IMAP calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="imap")

# Active background polling tasks: connector_id (str) → asyncio.Task
_poll_tasks: Dict[str, asyncio.Task] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _decode_header(value: Optional[str]) -> str:
    """Decode an RFC 2047-encoded header value to a plain string."""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded = []
    for fragment, charset in parts:
        if isinstance(fragment, bytes):
            decoded.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(fragment)
    return "".join(decoded)


def _imap_connect(connector: EmailConnector) -> imaplib.IMAP4:
    """Open and authenticate an IMAP connection (runs in thread pool)."""
    if connector.imap_use_ssl:
        conn = imaplib.IMAP4_SSL(connector.imap_host, connector.imap_port)
    else:
        conn = imaplib.IMAP4(connector.imap_host, connector.imap_port)
    conn.login(connector.imap_username, connector.imap_password)
    return conn


def _fetch_unseen(connector: EmailConnector) -> List[Dict[str, Any]]:
    """Poll the IMAP mailbox and return a list of unseen message dicts.

    Marks each fetched message as SEEN so it is not processed twice.
    Runs in the thread-pool executor — must not use asyncio primitives.
    """
    messages = []
    try:
        conn = _imap_connect(connector)
        conn.select(connector.imap_folder or "INBOX")
        status, data = conn.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            conn.logout()
            return messages
        msg_ids = data[0].split()
        for msg_id in msg_ids:
            try:
                _, raw = conn.fetch(msg_id, "(RFC822)")
                if not raw or not raw[0]:
                    continue
                raw_bytes = raw[0][1] if isinstance(raw[0], tuple) else raw[0]
                msg = email.message_from_bytes(raw_bytes)
                # Extract from
                from_raw = msg.get("From", "")
                name, addr = email.utils.parseaddr(from_raw)
                from_name = _decode_header(name) or addr
                # Extract subject
                subject = _decode_header(msg.get("Subject", ""))
                # Extract body
                body_text = ""
                body_html = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        if ctype == "text/plain" and not body_text:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body_text = payload.decode(charset, errors="replace") if payload else ""
                        elif ctype == "text/html" and not body_html:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body_html = payload.decode(charset, errors="replace") if payload else ""
                else:
                    payload = msg.get_payload(decode=True)
                    charset = msg.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace") if payload else ""

                messages.append({
                    "from_address": addr,
                    "from_name": from_name,
                    "subject": subject,
                    "body_text": body_text,
                    "body_html": body_html,
                    "reply_to": msg.get("Reply-To", addr),
                    "message_id": msg.get("Message-ID", ""),
                })
                # Mark as seen
                conn.store(msg_id, "+FLAGS", "\\Seen")
            except Exception as exc:
                _log.warning("IMAP: failed to parse message %s: %s", msg_id, exc)
        conn.logout()
    except Exception as exc:
        _log.error("IMAP poll error for connector %s: %s", connector.id, exc)
    return messages


async def _process_inbound_email(
    email_connector_id: str,
    from_address: str,
    from_name: str,
    subject: str,
    body_text: str,
    body_html: str,
    reply_to: str,
    message_id: str,
) -> Optional[str]:
    """Find the matching start_email node, create an Interaction and run the flow.

    Returns the session_key on success, None when no matching node is found.
    """
    from app.routers.inbound_router import _create_and_run_interaction, _find_entry_nodes, _resolve_connector

    async with async_session() as db:
        nodes = await _find_entry_nodes("start_email", db)

        matched_node: Optional[FlowNode] = None
        for node in nodes:
            cfg: dict = node.config or {}
            if str(cfg.get("connector_id", "")) != email_connector_id:
                continue
            # Optional: from_filter (substring match)
            from_filter = cfg.get("from_filter", "").strip()
            if from_filter and from_filter.lower() not in from_address.lower():
                continue
            # Optional: subject_filter (prefix match, case-insensitive)
            subj_filter = cfg.get("subject_filter", "").strip()
            if subj_filter and not subject.lower().startswith(subj_filter.lower()):
                continue
            matched_node = node
            break

        if not matched_node:
            _log.info(
                "inbound_email: no matching start_email node for connector=%s from=%s",
                email_connector_id, from_address,
            )
            return None

        cfg = matched_node.config or {}
        connector = await _resolve_connector(None, matched_node.flow_id, db)
        if not connector:
            _log.error(
                "inbound_email: no Connector linked to flow %s for email connector %s. "
                "Create a Connector record with flow_id=%s.",
                matched_node.flow_id, email_connector_id, matched_node.flow_id,
            )
            return None

        # Build initial context
        ctx: Dict[str, Any] = {}
        field_map = cfg.get("initial_variables") or {}
        source = {
            "from_address": from_address,
            "from_name": from_name,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "reply_to": reply_to,
            "message_id": message_id,
        }
        if isinstance(field_map, dict):
            for field, var in field_map.items():
                if var and field in source:
                    ctx[var] = source[field]
        # Always expose raw fields
        ctx.setdefault("from_address", from_address)
        ctx.setdefault("subject", subject)
        ctx.setdefault("body_text", body_text)

        # Unique session key per message
        msg_ref = message_id or f"{from_address}_{datetime.utcnow().isoformat()}"
        session_key = f"email_{email_connector_id[:8]}_{msg_ref}"[:128]

        visitor_metadata = {
            "channel": "email",
            "from_address": from_address,
            "from_name": from_name,
            "subject": subject,
            "message_id": message_id,
            "email_connector_id": email_connector_id,
        }

        await _create_and_run_interaction(
            connector=connector,
            flow_id=matched_node.flow_id,
            session_key=session_key,
            visitor_metadata=visitor_metadata,
            initial_ctx=ctx,
            db=db,
        )

    return session_key


# ─── Background IMAP poller ───────────────────────────────────────────────────

async def _poll_loop(connector_id: str, interval: int) -> None:
    """Async poll loop — runs in the background for one email connector."""
    loop = asyncio.get_event_loop()
    _log.info("IMAP poll loop started for connector %s (every %ds)", connector_id, interval)
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(EmailConnector).where(
                        EmailConnector.id == uuid.UUID(connector_id),
                        EmailConnector.is_active.is_(True),
                    )
                )
                ec = result.scalar_one_or_none()
            if not ec or not ec.imap_host or not ec.imap_username:
                _log.warning("IMAP poll: connector %s inactive or incomplete — stopping", connector_id)
                return

            # Fetch new messages in the thread pool
            messages = await loop.run_in_executor(_executor, _fetch_unseen, ec)
            if messages:
                _log.info("IMAP poll: %d new message(s) for connector %s", len(messages), connector_id)

            for msg in messages:
                try:
                    await _process_inbound_email(
                        email_connector_id=connector_id,
                        **msg,
                    )
                except Exception as exc:
                    _log.exception("IMAP: error processing message for connector %s: %s", connector_id, exc)

            # Update last_poll_at
            async with async_session() as db:
                result = await db.execute(select(EmailConnector).where(EmailConnector.id == uuid.UUID(connector_id)))
                ec2 = result.scalar_one_or_none()
                if ec2:
                    ec2.last_poll_at = datetime.utcnow()
                    await db.commit()

        except asyncio.CancelledError:
            _log.info("IMAP poll loop cancelled for connector %s", connector_id)
            return
        except Exception as exc:
            _log.exception("IMAP poll loop error for connector %s: %s", connector_id, exc)

        await asyncio.sleep(interval)


def _start_poll_task(connector_id: str, interval: int) -> None:
    """Start (or restart) the background polling task for a connector."""
    _stop_poll_task(connector_id)
    task = asyncio.create_task(_poll_loop(connector_id, interval))
    _poll_tasks[connector_id] = task
    _log.info("IMAP poll task started for connector %s", connector_id)


def _stop_poll_task(connector_id: str) -> None:
    """Cancel the background polling task for a connector if one is running."""
    existing = _poll_tasks.pop(connector_id, None)
    if existing and not existing.done():
        existing.cancel()
        _log.info("IMAP poll task cancelled for connector %s", connector_id)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[EmailConnectorOut])
async def list_email_connectors(db: AsyncSession = Depends(get_db)):
    """List all email connectors."""
    result = await db.execute(
        select(EmailConnector).order_by(EmailConnector.name)
    )
    return result.scalars().all()


@router.post("", response_model=EmailConnectorOut, status_code=201)
async def create_email_connector(
    body: EmailConnectorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new email connector.

    If IMAP credentials are complete and ``is_active`` is true the background
    poller starts automatically.
    """
    ec = EmailConnector(**body.model_dump())
    db.add(ec)
    await db.flush()
    await db.refresh(ec)
    await db.commit()

    if ec.is_active and ec.imap_host and ec.imap_username and ec.imap_password:
        _start_poll_task(str(ec.id), ec.poll_interval_seconds)

    return ec


@router.get("/{connector_id}", response_model=EmailConnectorOut)
async def get_email_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get one email connector by ID."""
    result = await db.execute(select(EmailConnector).where(EmailConnector.id == connector_id))
    ec = result.scalar_one_or_none()
    if not ec:
        raise HTTPException(status_code=404, detail="Email connector not found")
    return ec


@router.put("/{connector_id}", response_model=EmailConnectorOut)
async def update_email_connector(
    connector_id: uuid.UUID,
    body: EmailConnectorUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an email connector.  Restarts the poll task if IMAP settings changed."""
    result = await db.execute(select(EmailConnector).where(EmailConnector.id == connector_id))
    ec = result.scalar_one_or_none()
    if not ec:
        raise HTTPException(status_code=404, detail="Email connector not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(ec, field, val)

    await db.flush()
    await db.refresh(ec)
    await db.commit()

    # Restart or stop poll task based on new state
    if ec.is_active and ec.imap_host and ec.imap_username and ec.imap_password:
        _start_poll_task(str(ec.id), ec.poll_interval_seconds)
    else:
        _stop_poll_task(str(ec.id))

    return ec


@router.delete("/{connector_id}", status_code=204)
async def delete_email_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an email connector and stop its poll task."""
    result = await db.execute(select(EmailConnector).where(EmailConnector.id == connector_id))
    ec = result.scalar_one_or_none()
    if not ec:
        raise HTTPException(status_code=404, detail="Email connector not found")

    _stop_poll_task(str(connector_id))
    await db.delete(ec)
    await db.commit()


# ─── Test IMAP connection ──────────────────────────────────────────────────────

@router.post("/{connector_id}/test", summary="Test IMAP connectivity")
async def test_email_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Attempt to connect to the configured IMAP server and return the result.

    Does not fetch or modify any messages.
    """
    result = await db.execute(select(EmailConnector).where(EmailConnector.id == connector_id))
    ec = result.scalar_one_or_none()
    if not ec:
        raise HTTPException(status_code=404, detail="Email connector not found")

    if not ec.imap_host or not ec.imap_username or not ec.imap_password:
        return {"ok": False, "error": "IMAP host, username and password are required to test the connection."}

    loop = asyncio.get_event_loop()
    try:
        def _do_test():
            conn = _imap_connect(ec)
            status, login_data = conn.noop()
            conn.logout()
            return status

        imap_status = await loop.run_in_executor(_executor, _do_test)
        return {"ok": imap_status == "OK", "status": imap_status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ─── Inbound email webhook ────────────────────────────────────────────────────

class InboundEmailBody(BaseModel):
    """Inbound email payload posted by an SMTP webhook or forwarding rule."""
    email_connector_id: str              # UUID of the EmailConnector
    from_address: str
    from_name: Optional[str] = None
    subject: str = ""
    body_text: Optional[str] = ""
    body_html: Optional[str] = ""
    reply_to: Optional[str] = None
    message_id: Optional[str] = None


@router.post(
    "/inbound/email",
    tags=["inbound"],
    summary="Receive inbound email webhook",
    include_in_schema=True,
)
async def inbound_email_webhook(body: InboundEmailBody):
    """Process an inbound email notification: match to a ``start_email`` flow entry
    and route the thread into a queue the same way chat sessions are routed.

    This endpoint is also called internally by the IMAP poller.
    """
    session_key = await _process_inbound_email(
        email_connector_id=body.email_connector_id,
        from_address=body.from_address,
        from_name=body.from_name or "",
        subject=body.subject,
        body_text=body.body_text or "",
        body_html=body.body_html or "",
        reply_to=body.reply_to or body.from_address,
        message_id=body.message_id or "",
    )

    if session_key is None:
        return {"ok": False, "detail": "No matching flow found for this email."}

    return {"ok": True, "session_key": session_key}


# ─── Startup helper ───────────────────────────────────────────────────────────

async def start_all_poll_tasks() -> None:
    """Called from main.py lifespan to resume polling for all active connectors."""
    async with async_session() as db:
        result = await db.execute(
            select(EmailConnector).where(
                EmailConnector.is_active.is_(True),
            )
        )
        connectors = result.scalars().all()

    for ec in connectors:
        if ec.imap_host and ec.imap_username and ec.imap_password:
            _start_poll_task(str(ec.id), ec.poll_interval_seconds)
            _log.info("Resumed IMAP poll for connector '%s' (%s)", ec.name, ec.id)
    if connectors:
        _log.info("Email connector poll tasks: %d started", len(connectors))
