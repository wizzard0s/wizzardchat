"""Inbound event router — WhatsApp, Voice and API-trigger entry points.

Accepts external channel events, finds the matching flow entry node, creates
an Interaction and runs the flow.  The visitor-side SSE push from ``run_flow``
is fire-and-forget; the webhook acknowledges immediately.

Endpoints
---------
POST /api/v1/inbound/whatsapp
    Receive a WhatsApp message webhook.  Matches ``start_whatsapp`` entry nodes
    by connector_id and optional keyword/sender filters.

POST /api/v1/inbound/voice
    Receive an inbound-call event.  Matches ``start_voice`` entry nodes by
    connector_id and optional DID number filter.

POST /api/v1/flows/{flow_id}/trigger/{key}
    API-trigger entry point.  Calls the ``start_api`` node whose trigger_key
    equals ``key``.  Requires a valid Bearer token by default (configurable
    per-node with ``require_auth: false``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, optional_current_user
from app.database import async_session, get_db
from app.models import Connector, FlowNode, Interaction

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["inbound"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.utcnow().isoformat()


async def _find_entry_nodes(
    node_type: str,
    db: AsyncSession,
) -> List[FlowNode]:
    """Return all active FlowNodes of the given entry-point type."""
    result = await db.execute(
        select(FlowNode).where(FlowNode.node_type == node_type)
    )
    return result.scalars().all()


async def _resolve_connector(
    connector_id_str: Optional[str],
    flow_id,
    db: AsyncSession,
) -> Optional[Connector]:
    """Load a Connector record by explicit UUID or fall back to the flow's connector."""
    if connector_id_str:
        try:
            cid = uuid.UUID(connector_id_str)
        except (ValueError, AttributeError):
            return None
        result = await db.execute(
            select(Connector).where(Connector.id == cid, Connector.is_active.is_(True))
        )
        connector = result.scalar_one_or_none()
        if connector:
            return connector

    # Fall back: any active connector whose flow_id matches
    if flow_id:
        result = await db.execute(
            select(Connector).where(
                Connector.flow_id == flow_id,
                Connector.is_active.is_(True),
            )
        )
        return result.scalars().first()

    return None


async def _create_and_run_interaction(
    connector: Connector,
    flow_id,
    session_key: str,
    visitor_metadata: Dict[str, Any],
    initial_ctx: Dict[str, Any],
    db: AsyncSession,
) -> Interaction:
    """Persist a new Interaction, set flow context and fire run_flow."""
    from app.routers.chat_ws import _log_msg, _open_segment, run_flow

    ctx = dict(initial_ctx)
    ctx["_current_flow_id"] = str(flow_id)

    session = Interaction(
        connector_id=connector.id,
        session_key=session_key,
        visitor_metadata=visitor_metadata,
        flow_context=ctx,
        status="active",
        message_log=[],
        segments=[],
        channel=visitor_metadata.get("channel"),
        direction="inbound",
    )
    db.add(session)
    await db.flush()

    try:
        await run_flow(session, connector, db)
    except Exception as exc:
        _log.exception("inbound run_flow error for session %s: %s", session_key, exc)

    await db.commit()
    return session


# ─── WhatsApp ─────────────────────────────────────────────────────────────────

class WhatsAppInboundBody(BaseModel):
    """Payload sent by a WhatsApp Business API (or compatible) webhook."""
    connector_id: str                    # UUID of the WizzardChat Connector record
    from_number: str = ""               # Sender's phone number, e.g. +27821234567 — may be absent from 2026-03-31
    from_user_id: str = ""              # Meta Business-Scoped User ID (BSUID) — always present from 2026-03-31
    display_name: Optional[str] = None  # Contact display name from WhatsApp
    message_body: str = ""              # Text content (empty for media-only messages)
    media_url: Optional[str] = None     # Public URL of attached media
    message_id: Optional[str] = None   # WhatsApp message ID (for deduplication)


@router.post("/inbound/whatsapp", summary="Receive WhatsApp webhook")
async def inbound_whatsapp(body: WhatsAppInboundBody):
    """Match inbound WhatsApp message to a ``start_whatsapp`` flow entry node and run the flow.

    Matching order:
    1. ``connector_id`` in node config must equal the posted ``connector_id``.
    2. ``from_filter`` (if set) — sender number must be in the comma-separated list.
    3. ``keyword_filter`` (if set) — message_body must start with one of the keywords.

    The first node that satisfies all filters wins.
    """
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_whatsapp", db)

        matched_node: Optional[FlowNode] = None
        for node in nodes:
            cfg: dict = node.config or {}
            # Must match connector_id
            if str(cfg.get("connector_id", "")) != body.connector_id:
                continue
            # Optional: from_filter
            from_filter = cfg.get("from_filter", "").strip()
            if from_filter:
                allowed = [n.strip() for n in from_filter.split(",") if n.strip()]
                if body.from_number not in allowed:
                    continue
            # Optional: keyword_filter
            kw_filter = cfg.get("keyword_filter", "").strip()
            if kw_filter:
                keywords = [k.strip().lower() for k in kw_filter.split(",") if k.strip()]
                msg_lower = body.message_body.lower()
                if not any(msg_lower.startswith(kw) for kw in keywords):
                    continue
            matched_node = node
            break

        if not matched_node:
            _log.info(
                "inbound_whatsapp: no matching start_whatsapp node for connector=%s msg=%r",
                body.connector_id, body.message_body[:80],
            )
            return JSONResponse({"detail": "No matching flow for this WhatsApp message."}, status_code=200)

        connector = await _resolve_connector(body.connector_id, matched_node.flow_id, db)
        if not connector:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Connector '{body.connector_id}' not found or inactive. "
                    "Create a Connector record and link it to the start_whatsapp node."
                ),
            )

        # Build initial flow context from initial_variables mapping
        cfg = matched_node.config or {}
        ctx: Dict[str, Any] = {}
        field_map = cfg.get("initial_variables") or {}
        if isinstance(field_map, dict):
            source = {
                "from_number": body.from_number,
                "display_name": body.display_name or "",
                "message_body": body.message_body,
                "media_url": body.media_url or "",
            }
            for field, var in field_map.items():
                if var and field in source:
                    ctx[var] = source[field]
        # Always make raw fields available
        ctx.setdefault("from_number", body.from_number)
        ctx.setdefault("from_user_id", body.from_user_id)
        ctx.setdefault("message_body", body.message_body)

        # Session key: prefer phone number; fall back to BSUID for privacy-enabled users
        _sender_key = body.from_number or body.from_user_id
        dedup = body.message_id or _ts()
        session_key = f"wa_{body.connector_id[:8]}_{_sender_key}_{dedup}"[:128]

        visitor_metadata = {
            "channel": "whatsapp",
            "from_number": body.from_number,
            "from_user_id": body.from_user_id,
            "display_name": body.display_name,
            "message_id": body.message_id,
            "wa_connector_id": body.connector_id,
        }

        await _create_and_run_interaction(
            connector=connector,
            flow_id=matched_node.flow_id,
            session_key=session_key,
            visitor_metadata=visitor_metadata,
            initial_ctx=ctx,
            db=db,
        )

    return {"ok": True, "session_key": session_key}


# ─── Voice ────────────────────────────────────────────────────────────────────

class VoiceInboundBody(BaseModel):
    """Payload sent by a SIP/PBX/CPaaS platform on inbound call."""
    caller_id: str                       # Caller's CLID / ANI, e.g. +27821234567
    dialled_number: Optional[str] = None # DID the caller dialled — used for node matching
    connector_id: Optional[str] = None  # Optional: explicit Connector UUID (overrides DID match)
    call_id: Optional[str] = None       # Platform call identifier (for deduplication)
    metadata: Optional[Dict[str, Any]] = None  # Any extra call metadata


@router.post("/inbound/voice", summary="Receive inbound call event")
async def inbound_voice(body: VoiceInboundBody):
    """Match an inbound call to a ``start_voice`` flow entry node and run the IVR flow.

    Matching order:
    1. If ``connector_id`` is in the request, match nodes whose config ``connector_id`` equals it.
    2. Otherwise, match nodes whose ``did_number`` equals ``dialled_number``.
    3. Nodes with no ``did_number`` and no ``connector_id`` act as catch-all.

    The first matching node wins.
    """
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_voice", db)

        matched_node: Optional[FlowNode] = None
        for node in nodes:
            cfg: dict = node.config or {}
            node_connector_id = str(cfg.get("connector_id", "")).strip()
            node_did = str(cfg.get("did_number", "")).strip()

            if body.connector_id:
                # Explicit connector match
                if node_connector_id == body.connector_id:
                    matched_node = node
                    break
            elif body.dialled_number and node_did:
                # Match by DID number
                if node_did == body.dialled_number:
                    matched_node = node
                    break

        # Fall back to catch-all node (no DID, no connector_id configured)
        if not matched_node:
            for node in nodes:
                cfg = node.config or {}
                if not cfg.get("connector_id") and not cfg.get("did_number"):
                    matched_node = node
                    break

        if not matched_node:
            _log.info(
                "inbound_voice: no matching start_voice node for caller=%s did=%s",
                body.caller_id, body.dialled_number,
            )
            return JSONResponse({"detail": "No matching flow for this call."}, status_code=200)

        cfg = matched_node.config or {}
        connector = await _resolve_connector(
            cfg.get("connector_id") or body.connector_id,
            matched_node.flow_id,
            db,
        )
        if not connector:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No active Connector found for this voice entry. "
                    "Set connector_id on the start_voice node or create a Connector linked to the flow."
                ),
            )

        # Build initial context from initial_variables mapping
        ctx: Dict[str, Any] = {}
        caller_id_var = cfg.get("caller_id_variable") or "caller_id"
        dialled_var = cfg.get("dialled_variable") or "dialled_number"
        ctx[caller_id_var] = body.caller_id
        if body.dialled_number:
            ctx[dialled_var] = body.dialled_number
        if body.metadata:
            ctx.update(body.metadata)

        call_ref = body.call_id or _ts()
        session_key = f"voice_{body.caller_id}_{call_ref}"[:128]

        visitor_metadata = {
            "channel": "voice",
            "caller_id": body.caller_id,
            "dialled_number": body.dialled_number,
            "call_id": body.call_id,
        }

        await _create_and_run_interaction(
            connector=connector,
            flow_id=matched_node.flow_id,
            session_key=session_key,
            visitor_metadata=visitor_metadata,
            initial_ctx=ctx,
            db=db,
        )

    return {"ok": True, "session_key": session_key}


# ─── SMS ──────────────────────────────────────────────────────────────────────

class SmsInboundBody(BaseModel):
    """Payload sent by an SMS gateway (Twilio, Vonage, Africa's Talking, or generic HTTP webhook)."""
    connector_id: str                    # UUID of the SmsConnector record
    from_number: str                     # Sender's number, e.g. +27821234567
    to_number: Optional[str] = None      # Recipient (your long-code or short-code)
    message_body: str = ""               # SMS content
    message_id: Optional[str] = None    # Provider message ID (deduplication)
    metadata: Optional[Dict[str, Any]] = None   # Any extra fields from the provider


@router.post("/inbound/sms", summary="Receive inbound SMS")
async def inbound_sms(body: SmsInboundBody):
    """Match an inbound SMS to a ``start_sms`` flow entry node and run the flow.

    Matching order:
    1. ``connector_id`` in node config must equal the posted ``connector_id``.
    2. ``from_filter`` (if set) — sender number must be in the comma-separated list.
    3. ``keyword_filter`` (if set) — message_body must start with one of the keywords.

    The first node that satisfies all filters wins.
    """
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_sms", db)

        matched_node: Optional[FlowNode] = None
        for node in nodes:
            cfg: dict = node.config or {}
            if str(cfg.get("connector_id", "")) != body.connector_id:
                continue
            from_filter = cfg.get("from_filter", "").strip()
            if from_filter:
                allowed = [n.strip() for n in from_filter.split(",") if n.strip()]
                if body.from_number not in allowed:
                    continue
            kw_filter = cfg.get("keyword_filter", "").strip()
            if kw_filter:
                keywords = [k.strip().lower() for k in kw_filter.split(",") if k.strip()]
                msg_lower = body.message_body.lower()
                if not any(msg_lower.startswith(kw) for kw in keywords):
                    continue
            matched_node = node
            break

        if not matched_node:
            _log.info(
                "inbound_sms: no matching start_sms node for connector=%s from=%s",
                body.connector_id, body.from_number,
            )
            return JSONResponse({"detail": "No matching flow for this SMS."}, status_code=200)

        cfg = matched_node.config or {}
        connector = await _resolve_connector(
            cfg.get("connector_id") or body.connector_id,
            matched_node.flow_id,
            db,
        )
        if not connector:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No active Connector found for this SMS entry. "
                    "Set connector_id on the start_sms node or create a Connector linked to the flow."
                ),
            )

        # Build initial context
        ctx: Dict[str, Any] = {}
        initial_vars: Dict[str, str] = cfg.get("initial_variables") or {}
        field_map = {
            "from_number": body.from_number,
            "to_number": body.to_number or "",
            "message_body": body.message_body,
            "message_id": body.message_id or "",
        }
        for src_field, dest_var in initial_vars.items():
            if dest_var and src_field in field_map:
                ctx[dest_var] = field_map[src_field]
        ctx.setdefault("from_number", body.from_number)
        ctx.setdefault("message_body", body.message_body)
        if body.metadata:
            ctx.update(body.metadata)

        msg_ref = body.message_id or _ts()
        session_key = f"sms_{body.from_number}_{msg_ref}"[:128]

        visitor_metadata = {
            "channel": "sms",
            "from_number": body.from_number,
            "to_number": body.to_number,
            "message_id": body.message_id,
        }

        await _create_and_run_interaction(
            connector=connector,
            flow_id=matched_node.flow_id,
            session_key=session_key,
            visitor_metadata=visitor_metadata,
            initial_ctx=ctx,
            db=db,
        )

    return {"ok": True, "session_key": session_key}


# ─── API Trigger ──────────────────────────────────────────────────────────────

class ApiTriggerBody(BaseModel):
    """Payload for an API-triggered flow entry."""
    payload: Optional[Dict[str, Any]] = None  # Arbitrary data mapped via input_mapping
    session_key: Optional[str] = None          # Override the generated session key


@router.post(
    "/flows/{flow_id}/trigger/{key}",
    summary="API-trigger a flow entry point",
)
async def api_trigger_flow(
    flow_id: str,
    key: str,
    body: ApiTriggerBody,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(optional_current_user),
):
    """Trigger a ``start_api`` entry node by its ``trigger_key``.

    Authentication is required by default.  Set ``require_auth: false`` on the
    node to allow unauthenticated callers.

    The request body's ``payload`` fields are mapped to flow context variables
    using the node's ``input_mapping`` configuration.
    """
    # Load all start_api nodes in this flow
    try:
        fid = uuid.UUID(flow_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="flow_id must be a valid UUID")

    result = await db.execute(
        select(FlowNode).where(
            FlowNode.flow_id == fid,
            FlowNode.node_type == "start_api",
        )
    )
    candidates = result.scalars().all()

    matched_node: Optional[FlowNode] = None
    for node in candidates:
        cfg = node.config or {}
        if str(cfg.get("trigger_key", "")).strip() == key.strip():
            matched_node = node
            break

    if not matched_node:
        raise HTTPException(
            status_code=404,
            detail=f"No start_api node with trigger_key='{key}' found in flow {flow_id}.",
        )

    cfg = matched_node.config or {}

    # Auth check
    require_auth = cfg.get("require_auth", True)
    if require_auth and current_user is None:
        raise HTTPException(
            status_code=401,
            detail="This API entry point requires authentication. "
                   "Provide a valid Bearer token or set require_auth=false on the node.",
        )

    # Build context from input_mapping
    ctx: Dict[str, Any] = {}
    input_mapping = cfg.get("input_mapping") or {}
    payload = body.payload or {}
    if isinstance(input_mapping, dict):
        for field, var in input_mapping.items():
            if var and field in payload:
                ctx[var] = payload[field]
    # Always expose the raw payload
    ctx["_api_payload"] = payload

    connector = await _resolve_connector(
        cfg.get("connector_id"),
        fid,
        db,
    )
    if not connector:
        raise HTTPException(
            status_code=422,
            detail=(
                "No active Connector found for this API entry point. "
                "Create a Connector linked to this flow and optionally set connector_id on the node."
            ),
        )

    session_key = body.session_key or f"api_{flow_id[:8]}_{key}_{uuid.uuid4().hex[:8]}"
    session_key = session_key[:128]

    visitor_metadata = {
        "channel": "api",
        "trigger_key": key,
        "flow_id": flow_id,
        "triggered_by": str(current_user.id) if current_user else "anonymous",
    }

    session = await _create_and_run_interaction(
        connector=connector,
        flow_id=fid,
        session_key=session_key,
        visitor_metadata=visitor_metadata,
        initial_ctx=ctx,
        db=db,
    )

    return {
        "ok": True,
        "session_key": session_key,
        "interaction_id": str(session.id),
    }


# ─── Chat Ended Event ─────────────────────────────────────────────────────────

class ChatEndedBody(BaseModel):
    """Fired when a live-chat session closes.  Published internally by chat_ws.py."""
    session_key: str                         # Interaction.session_key of the closed session
    connector_id: Optional[str] = None       # UUID of the Connector
    closed_by: str = "unknown"               # "visitor" | "agent" | "timeout" | "wrap_up"
    channel: str = "chat"                    # "chat" | "whatsapp" | "sms" | etc.
    contact_id: Optional[str] = None
    queue_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/inbound/chat-ended", summary="Chat session closed event (internal)", include_in_schema=False)
async def inbound_chat_ended(body: ChatEndedBody):
    """Match a chat-ended event to ``start_chat_ended`` nodes and run their flows.

    Called internally when an Interaction status transitions to "closed" in chat_ws.py.
    Respects ``trigger_on`` filter (visitor_closed, agent_closed, timeout, wrap_up_completed, any).
    """
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_chat_ended", db)

        for node in nodes:
            cfg: dict = node.config or {}
            # Optional connector filter
            node_connector_id = str(cfg.get("connector_id", "")).strip()
            if node_connector_id and node_connector_id != (body.connector_id or ""):
                continue
            # trigger_on filter
            trigger_on = cfg.get("trigger_on", "any").strip()
            disposition_map = {
                "visitor_closed": "visitor",
                "agent_closed": "agent",
                "timeout": "timeout",
                "wrap_up_completed": "wrap_up",
            }
            if trigger_on != "any" and disposition_map.get(trigger_on) != body.closed_by:
                continue

            connector = await _resolve_connector(
                cfg.get("connector_id") or body.connector_id,
                node.flow_id,
                db,
            )
            if not connector:
                continue

            ctx: Dict[str, Any] = {}
            field_map = {
                "session_key": body.session_key,
                "connector_id": body.connector_id or "",
                "closed_by": body.closed_by,
                "channel": body.channel,
                "contact_id": body.contact_id or "",
                "queue_id": body.queue_id or "",
            }
            for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
                if dest_var and src_field in field_map:
                    ctx[dest_var] = field_map[src_field]
            ctx.setdefault("session_key", body.session_key)
            ctx.setdefault("closed_by", body.closed_by)
            if body.metadata:
                ctx.update(body.metadata)

            evt_session_key = f"chat_ended_{body.session_key}_{_ts()}"[:128]
            visitor_metadata = {"channel": "event", "trigger": "chat_ended", "closed_by": body.closed_by}
            try:
                await _create_and_run_interaction(
                    connector=connector,
                    flow_id=node.flow_id,
                    session_key=evt_session_key,
                    visitor_metadata=visitor_metadata,
                    initial_ctx=ctx,
                    db=db,
                )
            except Exception as exc:
                _log.exception("chat_ended flow error (node=%s): %s", node.id, exc)

    return {"ok": True}


# ─── Call Ended Event ─────────────────────────────────────────────────────────

class CallEndedBody(BaseModel):
    """Fired when a voice call completes.  Can be posted by the dialler or an external telephony webhook."""
    call_id: Optional[str] = None           # Provider call SID / ID
    connector_id: Optional[str] = None      # UUID of the VoiceConnector
    caller_id: Optional[str] = None         # E.164 caller number
    dialled_number: Optional[str] = None    # DID / destination number
    disposition: str = "completed"          # completed | no_answer | busy | failed
    duration_seconds: int = 0
    recording_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/inbound/call-ended", summary="Call ended event")
async def inbound_call_ended(body: CallEndedBody):
    """Match a call-ended event to ``start_call_ended`` nodes and run their flows."""
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_call_ended", db)

        for node in nodes:
            cfg: dict = node.config or {}
            node_connector_id = str(cfg.get("connector_id", "")).strip()
            if node_connector_id and node_connector_id != (body.connector_id or ""):
                continue
            trigger_on = cfg.get("trigger_on", "any").strip()
            if trigger_on != "any" and trigger_on != body.disposition:
                continue

            connector = await _resolve_connector(
                cfg.get("connector_id") or body.connector_id,
                node.flow_id,
                db,
            )
            if not connector:
                continue

            ctx: Dict[str, Any] = {}
            field_map = {
                "caller_id": body.caller_id or "",
                "dialled_number": body.dialled_number or "",
                "call_id": body.call_id or "",
                "duration_seconds": str(body.duration_seconds),
                "disposition": body.disposition,
                "recording_url": body.recording_url or "",
            }
            for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
                if dest_var and src_field in field_map:
                    ctx[dest_var] = field_map[src_field]
            ctx.setdefault("caller_id", body.caller_id or "")
            ctx.setdefault("disposition", body.disposition)
            if body.metadata:
                ctx.update(body.metadata)

            evt_session_key = f"call_ended_{body.call_id or body.caller_id}_{_ts()}"[:128]
            visitor_metadata = {"channel": "event", "trigger": "call_ended", "disposition": body.disposition}
            try:
                await _create_and_run_interaction(
                    connector=connector,
                    flow_id=node.flow_id,
                    session_key=evt_session_key,
                    visitor_metadata=visitor_metadata,
                    initial_ctx=ctx,
                    db=db,
                )
            except Exception as exc:
                _log.exception("call_ended flow error (node=%s): %s", node.id, exc)

    return {"ok": True}


# ─── SLA Breached Event ───────────────────────────────────────────────────────

class SlaBreachedBody(BaseModel):
    """Fired by the SLA monitor when a queued interaction exceeds its threshold."""
    interaction_id: str                      # UUID of the Interaction
    session_key: str
    queue_id: Optional[str] = None
    waited_seconds: int = 0
    breach_at: Optional[str] = None          # ISO timestamp of the breach
    metadata: Optional[Dict[str, Any]] = None


@router.post("/inbound/sla-breached", summary="SLA breach notification (internal)", include_in_schema=False)
async def inbound_sla_breached(body: SlaBreachedBody):
    """Match an SLA-breach event to ``start_sla_breached`` nodes and run their flows."""
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_sla_breached", db)

        for node in nodes:
            cfg: dict = node.config or {}
            node_queue_id = str(cfg.get("queue_id", "")).strip()
            if node_queue_id and node_queue_id != (body.queue_id or ""):
                continue
            threshold = int(cfg.get("sla_threshold_seconds") or 300)
            if body.waited_seconds < threshold:
                continue

            connector = await _resolve_connector(None, node.flow_id, db)
            if not connector:
                continue

            ctx: Dict[str, Any] = {}
            field_map = {
                "interaction_id": body.interaction_id,
                "session_key": body.session_key,
                "queue_id": body.queue_id or "",
                "waited_seconds": str(body.waited_seconds),
                "breach_at": body.breach_at or "",
            }
            for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
                if dest_var and src_field in field_map:
                    ctx[dest_var] = field_map[src_field]
            ctx.setdefault("interaction_id", body.interaction_id)
            ctx.setdefault("waited_seconds", str(body.waited_seconds))
            if body.metadata:
                ctx.update(body.metadata)

            evt_session_key = f"sla_breached_{body.session_key}_{_ts()}"[:128]
            visitor_metadata = {"channel": "event", "trigger": "sla_breached", "queue_id": body.queue_id}
            try:
                await _create_and_run_interaction(
                    connector=connector,
                    flow_id=node.flow_id,
                    session_key=evt_session_key,
                    visitor_metadata=visitor_metadata,
                    initial_ctx=ctx,
                    db=db,
                )
            except Exception as exc:
                _log.exception("sla_breached flow error (node=%s): %s", node.id, exc)

    return {"ok": True}


# ─── Contact Imported Event ───────────────────────────────────────────────────

class ContactImportedBody(BaseModel):
    """Fired when a contact is created or imported."""
    contact_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/inbound/contact-imported", summary="Contact created/imported event (internal)", include_in_schema=False)
async def inbound_contact_imported(body: ContactImportedBody):
    """Match a contact-imported event to ``start_contact_imported`` nodes and run their flows."""
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_contact_imported", db)

        for node in nodes:
            cfg: dict = node.config or {}
            connector = await _resolve_connector(None, node.flow_id, db)
            if not connector:
                continue

            ctx: Dict[str, Any] = {}
            field_map = {
                "contact_id": body.contact_id,
                "name": body.name or "",
                "email": body.email or "",
                "phone": body.phone or "",
                "company": body.company or "",
                "source": body.source or "",
                "tags": ",".join(body.tags or []),
            }
            for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
                if dest_var and src_field in field_map:
                    ctx[dest_var] = field_map[src_field]
            ctx.setdefault("contact_id", body.contact_id)
            ctx.setdefault("name", body.name or "")
            if body.metadata:
                ctx.update(body.metadata)

            evt_session_key = f"contact_import_{body.contact_id}_{_ts()}"[:128]
            visitor_metadata = {"channel": "event", "trigger": "contact_imported", "contact_id": body.contact_id}
            try:
                await _create_and_run_interaction(
                    connector=connector,
                    flow_id=node.flow_id,
                    session_key=evt_session_key,
                    visitor_metadata=visitor_metadata,
                    initial_ctx=ctx,
                    db=db,
                )
            except Exception as exc:
                _log.exception("contact_imported flow error (node=%s): %s", node.id, exc)

    return {"ok": True}


# ─── Contact Status Changed Event ─────────────────────────────────────────────

class ContactStatusChangedBody(BaseModel):
    """Fired when a contact's status field changes."""
    contact_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/inbound/contact-status-changed", summary="Contact status changed event (internal)", include_in_schema=False)
async def inbound_contact_status_changed(body: ContactStatusChangedBody):
    """Match a contact-status-changed event to ``start_contact_status_changed`` nodes."""
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_contact_status_changed", db)

        for node in nodes:
            cfg: dict = node.config or {}
            from_status = (cfg.get("from_status") or "").strip()
            to_status = (cfg.get("to_status") or "").strip()
            if from_status and from_status != (body.old_status or ""):
                continue
            if to_status and to_status != (body.new_status or ""):
                continue

            connector = await _resolve_connector(None, node.flow_id, db)
            if not connector:
                continue

            ctx: Dict[str, Any] = {}
            field_map = {
                "contact_id": body.contact_id,
                "name": body.name or "",
                "email": body.email or "",
                "phone": body.phone or "",
                "old_status": body.old_status or "",
                "new_status": body.new_status or "",
            }
            for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
                if dest_var and src_field in field_map:
                    ctx[dest_var] = field_map[src_field]
            ctx.setdefault("contact_id", body.contact_id)
            ctx.setdefault("old_status", body.old_status or "")
            ctx.setdefault("new_status", body.new_status or "")
            if body.metadata:
                ctx.update(body.metadata)

            evt_session_key = f"contact_status_{body.contact_id}_{_ts()}"[:128]
            visitor_metadata = {
                "channel": "event", "trigger": "contact_status_changed",
                "old_status": body.old_status, "new_status": body.new_status,
            }
            try:
                await _create_and_run_interaction(
                    connector=connector,
                    flow_id=node.flow_id,
                    session_key=evt_session_key,
                    visitor_metadata=visitor_metadata,
                    initial_ctx=ctx,
                    db=db,
                )
            except Exception as exc:
                _log.exception("contact_status_changed flow error (node=%s): %s", node.id, exc)

    return {"ok": True}


# ─── Internal Transfer ────────────────────────────────────────────────────────

class InternalTransferBody(BaseModel):
    """Fired by the Transfer node to hand off to a ``start_internal_call`` entry."""
    transfer_key: str                          # Must match start_internal_call node's transfer_key
    originating_session_key: Optional[str] = None
    caller_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None   # Flow variables to carry forward


@router.post("/inbound/transfer", summary="Internal flow transfer")
async def inbound_transfer(body: InternalTransferBody):
    """Match an internal-transfer request to a ``start_internal_call`` node and run the flow."""
    async with async_session() as db:
        nodes = await _find_entry_nodes("start_internal_call", db)

        matched_node = None
        for node in nodes:
            cfg: dict = node.config or {}
            if cfg.get("transfer_key", "").strip() == body.transfer_key.strip():
                matched_node = node
                break

        if not matched_node:
            raise HTTPException(
                status_code=404,
                detail=f"No start_internal_call node with transfer_key='{body.transfer_key}'."
            )

        connector = await _resolve_connector(None, matched_node.flow_id, db)
        if not connector:
            raise HTTPException(status_code=422, detail="No active connector for the target flow.")

        ctx: Dict[str, Any] = dict(body.context or {})
        cfg = matched_node.config or {}
        field_map = {
            "originating_session_key": body.originating_session_key or "",
            "caller_id": body.caller_id or "",
            "transfer_key": body.transfer_key,
        }
        for src_field, dest_var in (cfg.get("initial_variables") or {}).items():
            if dest_var and src_field in field_map:
                ctx.setdefault(dest_var, field_map[src_field])
        ctx.setdefault("caller_id", body.caller_id or "")

        session_key = f"transfer_{body.transfer_key}_{_ts()}"[:128]
        visitor_metadata = {
            "channel": "internal_transfer",
            "transfer_key": body.transfer_key,
            "from_session": body.originating_session_key,
        }
        session = await _create_and_run_interaction(
            connector=connector,
            flow_id=matched_node.flow_id,
            session_key=session_key,
            visitor_metadata=visitor_metadata,
            initial_ctx=ctx,
            db=db,
        )

    return {"ok": True, "session_key": session_key, "interaction_id": str(session.id)}


# ─── 3CX inbound webhook ──────────────────────────────────────────────────────

class ThreeCxInboundBody(BaseModel):
    """3CX CRM webhook payload (Ringing event for inbound calls).

    Configure the URL in the 3CX management console under
    Settings → CRM Integration → Webhook URL.
    """
    event:    str               # "Ringing" | "CallAnswered" | "CallEnded" | …
    callid:   str               # 3CX internal call ID
    caller:   Optional[str] = None   # Caller's number in E.164
    callee:   Optional[str] = None   # Dialled number in E.164
    duration: Optional[int] = None


@router.post("/inbound/3cx", summary="Receive 3CX inbound call webhook")
async def inbound_3cx(body: ThreeCxInboundBody):
    """Receive the 3CX Ringing event for an inbound call.

    Normalises the 3CX payload to ``VoiceInboundBody`` and delegates to the
    existing ``inbound_voice`` logic.  Only the first ``Ringing`` event creates
    an interaction; subsequent events (CallAnswered, CallEnded) are handled by
    the ``/api/v1/inbound/3cx`` event webhook in ``voice_twiml.py``.
    """
    if body.event != "Ringing":
        # Forward non-Ringing events to the twiml router via DB lookup
        return {"ok": True}

    normalised = VoiceInboundBody(
        caller_id=body.caller or "unknown",
        dialled_number=body.callee,
        call_id=body.callid,
        metadata={"provider": "3cx"},
    )
    return await inbound_voice(normalised)


# ─── FreeSWITCH mod_httapi inbound ────────────────────────────────────────────

@router.post("/inbound/freeswitch", summary="Receive FreeSWITCH mod_httapi inbound call")
async def inbound_freeswitch(request: Request):
    """Handle an inbound call forwarded by FreeSWITCH via mod_httapi.

    FreeSWITCH calls this URL when a contact dials a DID routed to the httapi
    dialplan application.  WizzardChat creates an Interaction, starts the
    matching flow, and returns XML that holds the caller on the line.

    Configure in your FreeSWITCH dialplan::

        <action application="httapi"
                data="{url=https://your-host/api/v1/inbound/freeswitch}"/>
    """
    from fastapi.responses import Response

    form = await request.form()
    caller    = str(form.get("Caller-Caller-ID-Number", "unknown"))
    callee    = str(form.get("Caller-Destination-Number", ""))
    unique_id = str(form.get("Unique-ID", ""))

    normalised = VoiceInboundBody(
        caller_id=caller,
        dialled_number=callee or None,
        call_id=unique_id or None,
        metadata={"provider": "freeswitch"},
    )
    await inbound_voice(normalised)

    # Return mod_httapi XML — hold the caller while the flow processes
    xml = (
        "<document type=\"xml/freeswitch-httapi\">"
        "<work>"
        "<pause milliseconds=\"30000\"/>"
        "</work>"
        "</document>"
    )
    return Response(content=xml, media_type="text/xml")


# ─── Asterisk ARI inbound (StasisStart via HTTP) ──────────────────────────────

class AsteriskAriEventBody(BaseModel):
    """Subset of an Asterisk ARI StasisStart event payload."""
    type:        str
    application: Optional[str] = None
    args:        List[str] = []
    channel: Optional[Dict[str, Any]] = None


@router.post("/inbound/asterisk/event", summary="Receive Asterisk ARI StasisStart event")
async def inbound_asterisk_event(body: AsteriskAriEventBody):
    """Handle an Asterisk ARI StasisStart event for an inbound call.

    Register this URL as the ARI HTTP event destination in ``ari.conf``::

        [wizzardchat]
        type = user
        password = <ari-password>
        allowed_origins = *

    For inbound calls, Asterisk fires ``StasisStart`` with an empty ``args``
    list.  WizzardChat normalises this to ``VoiceInboundBody`` and runs the
    matching flow.  Outbound ``StasisStart`` events (``args[0]`` = attempt_id)
    are forwarded to the ``/api/v1/voice/asterisk/event/{attempt_id}`` handler.
    """
    if body.type != "StasisStart":
        return {"ok": True}

    channel = body.channel or {}
    caller  = channel.get("caller", {}).get("number", "unknown")
    callee  = channel.get("dialplan", {}).get("exten", "")
    call_id = channel.get("id", "")

    # Outbound calls have attempt_id in args[0] — route to status handler
    if body.args:
        return {"ok": True, "note": "outbound StasisStart — handled by voice_twiml router"}

    normalised = VoiceInboundBody(
        caller_id=caller,
        dialled_number=callee or None,
        call_id=call_id or None,
        metadata={"provider": "asterisk"},
    )
    return await inbound_voice(normalised)
