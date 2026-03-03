"""
Chat communication layer — SSE (server→visitor) + HTTP POST (visitor→server).
Agent-to-server communication still uses WebSocket (internal / trusted network).

Visitor endpoints:
  GET  /sse/chat/{api_key}/{session_id}       — SSE stream (server push)
  POST /chat/{api_key}/{session_id}/init      — start session / trigger flow
  POST /chat/{api_key}/{session_id}/send      — visitor message
  POST /chat/{api_key}/{session_id}/typing    — visitor typing notification
  POST /chat/{api_key}/{session_id}/close     — visitor ends session

Agent endpoints (unchanged — internal WS):
  WS   /ws/agent?token={jwt}
"""

import json
import asyncio
import logging
import shutil
import uuid as _file_uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.database import async_session, get_db
from app.models import Connector, Interaction, FlowNode, FlowEdge, Flow, User, Queue, queue_agents
from app.config import get_settings
from app.auth import get_current_user
from app.routers.flows import (
    _resolve_template, _apply_set_variable, _evaluate_condition,
)

router = APIRouter(tags=["chat"])
_settings = get_settings()
_log = logging.getLogger("chat_ws")

# Directory for uploaded chat files — created by main.py lifespan
UPLOADS_DIR = Path("static/uploads/chat")


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _settings.secret_key, algorithms=[_settings.algorithm])
    except JWTError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# In-memory connection registry
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # session_key → asyncio.Queue  (visitor SSE push channel)
        self.visitor_queues: Dict[str, asyncio.Queue] = {}
        # user_id (str) → WebSocket  (agent WS — unchanged)
        self.agents: Dict[str, WebSocket] = {}
        # user_id → campaign_id (str UUID)
        self.agent_campaigns: Dict[str, Optional[str]] = {}
        # user_id → active session count (for least-busy dispatch)
        self.agent_load: Dict[str, int] = {}
        # user_id → availability status: "available" | "admin" | "lunch" | "break" | etc.
        self.agent_availability: Dict[str, str] = {}

    # ── Visitor SSE channel ───────────────────────────────────────────────────

    def register_visitor_sse(self, session_key: str) -> asyncio.Queue:
        """Create (or replace) the SSE queue for a visitor session."""
        q: asyncio.Queue = asyncio.Queue()
        self.visitor_queues[session_key] = q
        return q

    def disconnect_visitor(self, session_key: str):
        self.visitor_queues.pop(session_key, None)

    async def send_visitor(self, session_key: str, data: dict):
        """Enqueue a message for the visitor's SSE stream. Silently drops if offline."""
        q = self.visitor_queues.get(session_key)
        if q:
            try:
                await q.put(data)
            except Exception:
                pass

    # ── Agent WebSocket ───────────────────────────────────────────────────────

    async def connect_agent(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.agents[user_id] = ws
        self.agent_load.setdefault(user_id, 0)
        self.agent_campaigns.setdefault(user_id, None)
        self.agent_availability.setdefault(user_id, "offline")

    def disconnect_agent(self, user_id: str):
        self.agents.pop(user_id, None)
        self.agent_load.pop(user_id, None)
        # Keep agent_campaigns and agent_availability so they persist across reconnects.
        # On reconnect, setdefault won't override the existing value.

    async def send_agent(self, user_id: str, data: dict):
        ws = self.agents.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                self.disconnect_agent(user_id)

    async def broadcast_to_agents(self, data: dict):
        dead = []
        for uid, ws in list(self.agents.items()):
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.agents.pop(uid, None)


manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────────────
# Agent availability & dispatch helpers
# ─────────────────────────────────────────────────────────────────────────────

import uuid as _uuid_mod

async def _find_available_agent(
    queue_id: Optional[str], db: AsyncSession
) -> Optional[str]:
    """
    Find the least-busy online agent for a given queue.
    Priority:
      1. Agents explicitly assigned to the queue (queue_agents table)
      2. Agents whose active campaign matches the queue's campaign_id
      3. Any online agent (fallback)
    Returns user_id string or None.
    """
    # Only agents with "available" status can receive sessions
    online_ids = {
        uid for uid in manager.agents.keys()
        if manager.agent_availability.get(uid, "offline") == "available"
    }
    if not online_ids:
        return None

    def least_busy(candidates: set) -> str:
        return min(candidates, key=lambda uid: manager.agent_load.get(uid, 0))

    campaign_id_str: Optional[str] = None

    if queue_id:
        try:
            q_uuid = _uuid_mod.UUID(queue_id)
        except ValueError:
            q_uuid = None

        if q_uuid:
            # 1. Queue-member agents that are online
            res = await db.execute(
                select(queue_agents.c.user_id)
                .where(queue_agents.c.queue_id == q_uuid)
            )
            member_ids = {str(r[0]) for r in res.all()}
            available = member_ids & online_ids
            if available:
                return least_busy(available)

            # Fetch campaign_id from the queue
            q_res = await db.execute(select(Queue).where(Queue.id == q_uuid))
            q_obj = q_res.scalar_one_or_none()
            if q_obj and q_obj.campaign_id:
                campaign_id_str = str(q_obj.campaign_id)

    # 2. Agents whose campaign preference matches
    if campaign_id_str:
        campaign_agents = {
            uid for uid, cid in manager.agent_campaigns.items()
            if cid == campaign_id_str and uid in online_ids
        }
        if campaign_agents:
            return least_busy(campaign_agents)

    # 3. Any online agent (fallback)
    return least_busy(online_ids)


async def _auto_assign_session(
    session: Interaction, db: AsyncSession
) -> bool:
    """
    Try to auto-assign a waiting session to an available agent.
    Returns True if an agent was assigned.
    """
    queue_id_str = str(session.queue_id) if session.queue_id else None
    agent_uid = await _find_available_agent(queue_id_str, db)
    if not agent_uid:
        return False

    session.agent_id = _uuid_mod.UUID(agent_uid)
    session.status = "with_agent"
    await db.flush()

    agent_res = await db.execute(select(User).where(User.id == session.agent_id))
    agent = agent_res.scalar_one_or_none()
    agent_name = agent.full_name if agent else "Agent"

    manager.agent_load[agent_uid] = manager.agent_load.get(agent_uid, 0) + 1

    # Tell visitor
    await manager.send_visitor(session.session_key, {
        "type": "agent_join",
        "agent_name": agent_name,
        "timestamp": _ts(),
    })
    # Tell agent
    await manager.send_agent(agent_uid, {
        "type": "session_assigned",
        "session": _session_summary(session, ""),
    })
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _log_msg(session: Interaction, from_: str, text: str, subtype: str = "message", filename: str = ""):
    """Append an entry to session.message_log (in-memory; caller must flush/commit)."""
    log = list(session.message_log or [])
    entry: dict = {"from": from_, "text": text, "ts": _ts(), "subtype": subtype}
    if filename:
        entry["filename"] = filename
    log.append(entry)
    session.message_log = log


def _session_summary(session: Interaction, connector_name: str = "") -> dict:
    meta = session.visitor_metadata or {}
    return {
        "id": str(session.id),
        "session_key": session.session_key,
        "connector_id": str(session.connector_id),
        "connector_name": connector_name,
        "status": session.status,
        "visitor_name": meta.get("name", meta.get("visitor_name", "Visitor")),
        "visitor_email": meta.get("email", ""),
        "page_url": meta.get("page_url", ""),
        "metadata": meta,
        "created_at": session.created_at.isoformat() + "Z",
        "last_activity_at": (session.last_activity_at.isoformat() + "Z") if session.last_activity_at else None,
        "agent_id": str(session.agent_id) if session.agent_id else None,
        "message_log": list(session.message_log or []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Flow runner
# ─────────────────────────────────────────────────────────────────────────────

async def _load_flow_graph(flow_id, db: AsyncSession):
    nodes_result = await db.execute(select(FlowNode).where(FlowNode.flow_id == flow_id))
    nodes: Dict[str, FlowNode] = {str(n.id): n for n in nodes_result.scalars().all()}
    edges_result = await db.execute(select(FlowEdge).where(FlowEdge.flow_id == flow_id))
    edges = list(edges_result.scalars().all())
    return nodes, edges


def _next_node_id(edges, node_id: str, handle: str = "default") -> Optional[str]:
    outs = [e for e in edges if str(e.source_node_id) == node_id]
    if not outs:
        return None
    for e in outs:
        if (e.source_handle or "default") == handle:
            return str(e.target_node_id)
    return str(outs[0].target_node_id)


async def run_flow(session: Interaction, connector: Connector, db: AsyncSession):
    """
    Execute the linked flow starting from:
    - The node AFTER the waiting node (if resuming)
    - The node AFTER the start node (if fresh)

    Execute the linked flow, pushing messages to the visitor's SSE queue.
    Pauses at input/queue nodes and persists state to DB.
    """
    if not connector.flow_id:
        await manager.send_visitor(session.session_key, {
            "type": "message", "from": "bot",
            "text": "This connector has no flow configured.", "timestamp": _ts(),
        })
        return

    ctx: dict = dict(session.flow_context or {})

    # If we paused inside a sub-flow, resume from that flow's graph
    _resume_flow_id = ctx.get("_current_flow_id") or str(connector.flow_id)
    nodes, edges = await _load_flow_graph(_resume_flow_id, db)

    # Determine starting point
    if session.waiting_node_id and session.waiting_node_id in nodes:
        current_id = _next_node_id(edges, session.waiting_node_id)
        session.waiting_node_id = None
    else:
        start = next((n for n in nodes.values() if n.node_type == "start"), None)
        if not start:
            await manager.send_visitor(session.session_key, {
                "type": "error", "message": "Flow has no start node.", "timestamp": _ts(),
            })
            return
        current_id = _next_node_id(edges, str(start.id))

    send = lambda data: manager.send_visitor(session.session_key, data)

    for _step in range(200):  # safety limit (sub-flows add extra steps)
        if not current_id or current_id not in nodes:
            break

        node = nodes[current_id]
        config: dict = node.config or {}

        # ── End ──────────────────────────────────────────────────────────────
        if node.node_type == "end":
            call_stack = ctx.get("_call_stack", [])
            if call_stack:
                # End of a sub-flow — pop back to parent and continue
                frame = call_stack.pop()
                ctx["_call_stack"] = call_stack
                parent_flow_id = frame["flow_id"]
                ctx["_current_flow_id"] = parent_flow_id
                _resume_flow_id = parent_flow_id
                nodes, edges = await _load_flow_graph(parent_flow_id, db)
                current_id = frame["return_node_id"]
                continue
            # Normal top-level end
            msg_text = _resolve_template(config.get("message", ""), ctx)
            await send({
                "type": "end",
                "status": config.get("status", "completed"),
                "message": msg_text,
                "timestamp": _ts(),
            })
            if msg_text:
                _log_msg(session, "system", msg_text, subtype="end")
            ctx.pop("_current_flow_id", None)
            ctx.pop("_call_stack", None)
            session.status = "closed"
            session.flow_context = ctx
            await db.flush()
            return

        # ── Message ───────────────────────────────────────────────────────────
        elif node.node_type == "message":
            text = _resolve_template(config.get("text", ""), ctx)
            await send({"type": "message", "from": "bot", "text": text, "timestamp": _ts()})
            _log_msg(session, "bot", text)
            current_id = _next_node_id(edges, current_id)

        # ── Input (free text) ─────────────────────────────────────────────────
        elif node.node_type == "input":
            prompt = _resolve_template(config.get("prompt", config.get("text", "")), ctx)
            if prompt:
                await send({"type": "message", "from": "bot", "text": prompt, "timestamp": _ts()})
                _log_msg(session, "bot", prompt)
            session.waiting_node_id = current_id
            session.flow_context = ctx
            await db.flush()
            return  # resume via handle_visitor_message()

        # ── DTMF / single-key input ───────────────────────────────────────────
        elif node.node_type == "dtmf":
            prompt = _resolve_template(config.get("prompt", ""), ctx)
            if prompt:
                await send({"type": "message", "from": "bot", "text": prompt, "timestamp": _ts()})
                _log_msg(session, "bot", prompt)
            session.waiting_node_id = current_id
            session.flow_context = ctx
            await db.flush()
            return

        # ── Menu / choice ─────────────────────────────────────────────────────
        elif node.node_type == "menu":
            text = _resolve_template(config.get("prompt", config.get("text", "")), ctx)
            options = config.get("options", [])
            await send({"type": "menu", "text": text, "options": options, "timestamp": _ts()})
            # Log menu as bot message with options appended
            opts_text = "  |  ".join(f"{o.get('key','?')}. {o.get('text','')}" for o in options)
            _log_msg(session, "bot", f"{text}\n{opts_text}" if opts_text else text, subtype="menu")
            session.waiting_node_id = current_id
            session.flow_context = ctx
            await db.flush()
            return

        # ── Set Variable ──────────────────────────────────────────────────────
        elif node.node_type == "set_variable":
            ctx = _apply_set_variable(ctx, config)
            current_id = _next_node_id(edges, current_id)

        # ── Condition ─────────────────────────────────────────────────────────
        elif node.node_type == "condition":
            result = _evaluate_condition(ctx, config)
            current_id = _next_node_id(edges, current_id, "true" if result else "false")

        # ── Queue / Transfer (hand off to human agent) ────────────────────────
        elif node.node_type in ("queue", "transfer", "queue_transfer"):
            # Resolve queue_id from config (supports both old queue_name and new queue_id)
            raw_queue_id = config.get("queue_id") or config.get("queue_name", "")
            msg = _resolve_template(
                config.get("queue_message", "Connecting you with an agent, please wait…"), ctx
            )
            await send({"type": "queue", "message": msg, "timestamp": _ts()})

            # Persist queue reference on session
            if raw_queue_id:
                try:
                    session.queue_id = _uuid_mod.UUID(str(raw_queue_id))
                except ValueError:
                    pass  # not a valid UUID – might be a queue name, ignore for now

            session.status = "waiting_agent"
            session.waiting_node_id = current_id
            session.flow_context = ctx
            _log_msg(session, "system", msg, subtype="queue")
            await db.flush()

            # Try instant dispatch to an available agent
            assigned = await _auto_assign_session(session, db)
            if not assigned:
                # Broadcast to all agents so manual take is possible
                await manager.broadcast_to_agents({
                    "type": "new_session",
                    "session": _session_summary(session, ""),
                })
            return

        # ── GoTo ──────────────────────────────────────────────────────────────
        elif node.node_type == "goto":
            target = config.get("target_node", "")
            found = next(
                (str(n.id) for n in nodes.values()
                 if (n.label or "") == target or str(n.id) == target),
                None,
            )
            if found:
                current_id = found
            else:
                break  # broken goto

        # ── Sub-Flow ──────────────────────────────────────────────────────────
        elif node.node_type == "sub_flow":
            target_flow_id = config.get("flow_id")
            if not target_flow_id:
                # No flow configured — skip silently
                current_id = _next_node_id(edges, current_id)
            else:
                # Push a return frame so we come back here when the sub-flow ends
                return_node_id = _next_node_id(edges, current_id)
                call_stack = list(ctx.get("_call_stack") or [])
                call_stack.append({
                    "flow_id": str(_resume_flow_id),
                    "return_node_id": return_node_id,
                })
                ctx["_call_stack"] = call_stack
                ctx["_current_flow_id"] = str(target_flow_id)
                _resume_flow_id = str(target_flow_id)
                nodes, edges = await _load_flow_graph(target_flow_id, db)
                sub_start = next((n for n in nodes.values() if n.node_type == "start"), None)
                if not sub_start:
                    # Sub-flow has no start — pop frame and skip
                    call_stack.pop()
                    ctx["_call_stack"] = call_stack
                    ctx["_current_flow_id"] = call_stack[-1]["flow_id"] if call_stack else str(connector.flow_id)
                    nodes, edges = await _load_flow_graph(ctx["_current_flow_id"], db)
                    _resume_flow_id = ctx["_current_flow_id"]
                    current_id = return_node_id
                else:
                    current_id = _next_node_id(edges, str(sub_start.id))

        # ── All other nodes – pass-through ────────────────────────────────────
        else:
            current_id = _next_node_id(edges, current_id)

    session.flow_context = ctx
    await db.flush()


async def handle_visitor_message(session: Interaction, connector: Connector,
                                  text: str, db: AsyncSession):
    """Process input text from a visitor and advance the flow."""
    # Always log the visitor's message
    _log_msg(session, "visitor", text)

    if session.status == "with_agent" and session.agent_id:
        # Forward directly to the assigned agent
        await manager.send_agent(str(session.agent_id), {
            "type": "message",
            "session_id": session.session_key,
            "from": "visitor",
            "text": text,
            "timestamp": _ts(),
        })
        return

    # During flow: broadcast visitor text to all connected agents so they see
    # real-time flow activity without needing to reload the session.
    await manager.broadcast_to_agents({
        "type": "message",
        "session_id": session.session_key,
        "from": "visitor",
        "text": text,
        "timestamp": _ts(),
    })

    if session.waiting_node_id:
        # Load nodes to determine which type we're paused at
        nodes, edges = await _load_flow_graph(connector.flow_id, db)
        waiting_node = nodes.get(session.waiting_node_id)
        ctx = dict(session.flow_context or {})

        if waiting_node:
            config = waiting_node.config or {}
            if waiting_node.node_type in ("input", "dtmf"):
                variable = config.get("variable", "input")
                ctx[variable] = text

            elif waiting_node.node_type == "menu":
                variable = config.get("variable", "selection")
                options = config.get("options", [])
                matched_key = text
                for opt in options:
                    if (str(opt.get("key", "")).lower() == text.lower()
                            or opt.get("text", "").lower() == text.lower()):
                        matched_key = str(opt.get("key", text))
                        break
                ctx[variable] = matched_key

        session.flow_context = ctx

    # Continue executing the flow
    await run_flow(session, connector, db)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic bodies
# ─────────────────────────────────────────────────────────────────────────────

class InitBody(BaseModel):
    metadata: dict = {}


class SendBody(BaseModel):
    text: str


# ─────────────────────────────────────────────────────────────────────────────
# Shared session loader
# ─────────────────────────────────────────────────────────────────────────────

async def _load_connector_and_session(
    api_key: str, session_id: str, db: AsyncSession, create_if_missing: bool = False
):
    """Returns (connector, session, is_new). connector is None if invalid."""
    res = await db.execute(select(Connector).where(Connector.api_key == api_key))
    connector = res.scalar_one_or_none()
    if not connector or not connector.is_active:
        return None, None, False

    res2 = await db.execute(select(Interaction).where(Interaction.session_key == session_id))
    session = res2.scalar_one_or_none()
    is_new = session is None

    if is_new and create_if_missing:
        session = Interaction(
            connector_id=connector.id,
            session_key=session_id,
            visitor_metadata={},
            flow_context={},
            status="active",
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)

    return connector, session, is_new


# ─────────────────────────────────────────────────────────────────────────────
# SSE stream  GET /sse/chat/{api_key}/{session_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sse/chat/{api_key}/{session_id}")
async def visitor_sse(api_key: str, session_id: str):
    """
    Server-Sent Events stream for visitor.
    Widget opens this first; once 'connected'/'resumed' arrives it POSTs /init.
    A closed session is transparently reset so re-opening the widget works.
    """
    try:
        async with async_session() as db:
            # Validate connector
            res = await db.execute(select(Connector).where(Connector.api_key == api_key))
            connector = res.scalar_one_or_none()
            if not connector or not connector.is_active:
                _log.warning("SSE: invalid/inactive connector key=%s", api_key)
                return JSONResponse({"detail": "Invalid or inactive connector"}, status_code=401)

            # Load existing session
            res2 = await db.execute(select(Interaction).where(Interaction.session_key == session_id))
            session = res2.scalar_one_or_none()

            if session is None:
                # Brand-new session
                session = Interaction(
                    connector_id=connector.id,
                    session_key=session_id,
                    visitor_metadata={},
                    flow_context={},
                    status="active",
                )
                db.add(session)
                await db.flush()
                await db.refresh(session)
                is_new = True
            elif session.status == "closed":
                # Allow visitor to reopen a closed session as a fresh one
                session.status = "active"
                session.flow_context = {}
                session.visitor_metadata = {}
                session.waiting_node_id = None
                session.agent_id = None
                session.queue_id = None
                await db.flush()
                is_new = True   # treat as new so /init re-runs the flow
            else:
                is_new = False

            connector_style = connector.style or {}
            session_key = session.session_key
            await db.commit()
    except Exception as e:
        _log.exception("SSE: DB error setting up session: %s", e)
        return JSONResponse({"detail": "Server error"}, status_code=500)

    q = manager.register_visitor_sse(session_key)
    await q.put({
        "type": "connected" if is_new else "resumed",
        "session_id": session_id,
        "config": connector_style,
        "timestamp": _ts(),
    })

    async def event_stream():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"   # keep proxy/firewall alive
                except (asyncio.CancelledError, GeneratorExit):
                    return
                except Exception as inner_err:
                    _log.exception("SSE event_stream inner error: %s", inner_err)
                    yield f"data: {json.dumps({'type':'error','message':'Server error'})}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as outer_err:
            _log.exception("SSE event_stream outer error: %s", outer_err)
        finally:
            manager.disconnect_visitor(session_key)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Init  POST /chat/{api_key}/{session_id}/init
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/{api_key}/{session_id}/init")
async def visitor_init(api_key: str, session_id: str, body: InitBody):
    """Set visitor metadata and start the flow (new sessions only)."""
    async with async_session() as db:
        connector, session, is_new = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=True
        )
        if not connector or not session:
            return JSONResponse({"detail": "Not found"}, status_code=404)

        metadata = body.metadata or {}
        session.visitor_metadata = metadata

        ctx = dict(session.flow_context or {})
        for mf in (connector.meta_fields or []):
            field_name = mf.get("name", "")
            var_name = mf.get("map_to_variable", "") or field_name
            if field_name and field_name in metadata and var_name:
                ctx[var_name] = metadata[field_name]
        session.flow_context = ctx
        await db.flush()

        if is_new or session.status == "active":
            try:
                await run_flow(session, connector, db)
            except Exception as e:
                _log.exception("run_flow error in init: %s", e)
                await manager.send_visitor(session_id, {
                    "type": "error",
                    "message": "Flow error – please contact support.",
                    "timestamp": _ts(),
                })

        await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Send  POST /chat/{api_key}/{session_id}/send
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/{api_key}/{session_id}/send")
async def visitor_send(api_key: str, session_id: str, body: SendBody):
    """Visitor message — advances the flow or forwards to agent."""
    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"detail": "Empty message"}, status_code=400)

    async with async_session() as db:
        connector, session, _ = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=False
        )
        if not connector or not session:
            return JSONResponse({"detail": "Session not found"}, status_code=404)
        if session.status == "closed":
            return JSONResponse({"detail": "Session closed"}, status_code=410)

        # NOTE: do NOT forward to agent here — handle_visitor_message does it
        # to avoid double-delivery when status == "with_agent".
        try:
            await handle_visitor_message(session, connector, text, db)
        except Exception as e:
            _log.exception("handle_visitor_message error: %s", e)

        await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Typing  POST /chat/{api_key}/{session_id}/typing
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/{api_key}/{session_id}/typing")
async def visitor_typing(api_key: str, session_id: str):
    """Notify assigned agent that visitor is typing."""
    async with async_session() as db:
        _, session, _ = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=False
        )
        if session and session.agent_id:
            await manager.send_agent(str(session.agent_id), {
                "type": "typing",
                "session_id": session_id,
                "from": "visitor",
            })
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Close  POST /chat/{api_key}/{session_id}/close
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/{api_key}/{session_id}/close")
async def visitor_close(api_key: str, session_id: str):
    """Visitor explicitly ends the session."""
    async with async_session() as db:
        _, session, _ = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=False
        )
        if session:
            if session.agent_id:
                await manager.send_agent(str(session.agent_id), {
                    "type": "session_closed",
                    "session_id": session_id,
                })
            session.status = "closed"
            await db.commit()
        manager.disconnect_visitor(session_id)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Visitor file upload  POST /chat/{api_key}/{session_id}/upload
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/{api_key}/{session_id}/upload")
async def visitor_upload(api_key: str, session_id: str, file: UploadFile = File(...)):
    """Visitor uploads a file attachment; saved to static/uploads/chat/ and broadcast to agent."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "file").suffix or ""
    safe_name = _file_uuid.uuid4().hex + ext
    dest = UPLOADS_DIR / safe_name
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as e:
        _log.error("visitor_upload save error: %s", e)
        return JSONResponse({"detail": "Upload failed"}, status_code=500)
    url = "/static/uploads/chat/" + safe_name
    filename = file.filename or safe_name

    async with async_session() as db:
        _, session, _ = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=False
        )
        if session and session.status != "closed":
            _log_msg(session, "visitor", url, subtype="attachment", filename=filename)
            msg_payload = {
                "type": "message",
                "session_id": session_id,
                "from": "visitor",
                "text": url,
                "subtype": "attachment",
                "filename": filename,
                "timestamp": _ts(),
            }
            # Forward to assigned agent or broadcast to all agents during flow
            if session.agent_id:
                await manager.send_agent(str(session.agent_id), msg_payload)
            else:
                await manager.broadcast_to_agents(msg_payload)
            await db.commit()
    return {"ok": True, "url": url, "filename": filename}


# ─────────────────────────────────────────────────────────────────────────────
# Agent file upload  POST /api/v1/sessions/{session_id}/attachment
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/v1/sessions/{session_id}/attachment")
async def agent_upload(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Agent uploads a file attachment; saved and pushed to visitor SSE."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "file").suffix or ""
    safe_name = _file_uuid.uuid4().hex + ext
    dest = UPLOADS_DIR / safe_name
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as e:
        _log.error("agent_upload save error: %s", e)
        return JSONResponse({"detail": "Upload failed"}, status_code=500)
    url = "/static/uploads/chat/" + safe_name
    filename = file.filename or safe_name

    sess_res = await db.execute(select(Interaction).where(Interaction.session_key == session_id))
    session = sess_res.scalar_one_or_none()
    if session and session.status != "closed":
        _log_msg(session, "agent", url, subtype="attachment", filename=filename)
        await manager.send_visitor(session_id, {
            "type": "message",
            "from": "agent",
            "text": url,
            "subtype": "attachment",
            "filename": filename,
            "timestamp": _ts(),
        })
        await db.commit()
    return {"ok": True, "url": url, "filename": filename}


# ─────────────────────────────────────────────────────────────────────────────
# Agent WebSocket  /ws/agent?token={jwt}
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket, token: str = Query(...)):
    # Authenticate
    payload = _decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Missing user id")
        return

    await manager.connect_agent(user_id, websocket)

    async with async_session() as db:
        # Send current waiting/active sessions immediately
        res = await db.execute(
            select(Interaction, Connector)
            .join(Connector, Interaction.connector_id == Connector.id)
            .where(Interaction.status.in_(["active", "waiting_agent", "with_agent"]))
            .order_by(Interaction.created_at.desc())
        )
        sessions_data = []
        for sess, conn in res.all():
            sessions_data.append(_session_summary(sess, conn.name))

        await websocket.send_text(json.dumps({
            "type": "sessions",
            "data": sessions_data,
        }))

        # Send current availability so UI stays in sync on reconnect
        await websocket.send_text(json.dumps({
            "type": "availability_set",
            "status": manager.agent_availability.get(user_id, "offline"),
        }))

        # Auto-select campaign if the agent belongs to exactly one
        try:
            cq_res = await db.execute(
                select(Queue.campaign_id)
                .join(queue_agents, queue_agents.c.queue_id == Queue.id)
                .where(queue_agents.c.user_id == _uuid_mod.UUID(user_id))
                .where(Queue.campaign_id.isnot(None))
            )
            agent_campaign_ids = list({str(r[0]) for r in cq_res.all()})
            if len(agent_campaign_ids) == 1 and not manager.agent_campaigns.get(user_id):
                auto_cid = agent_campaign_ids[0]
                manager.agent_campaigns[user_id] = auto_cid
                await websocket.send_text(json.dumps({
                    "type": "campaign_set",
                    "campaign_id": auto_cid,
                    "auto_selected": True,
                }))
        except Exception as _ae:
            _log.warning("Auto-campaign detection failed: %s", _ae)

        try:
            async for raw in websocket.iter_text():
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                # ── Take a session (agent picks up a waiting visitor) ──────────
                if msg_type == "take":
                    session_key = msg.get("session_id", "")
                    res2 = await db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    sess = res2.scalar_one_or_none()
                    if sess:
                        sess.agent_id = _uuid_mod.UUID(user_id)
                        sess.status = "with_agent"
                        await db.flush()
                        # Get agent name
                        agent_res = await db.execute(select(User).where(User.id == sess.agent_id))
                        agent = agent_res.scalar_one_or_none()
                        agent_name = agent.full_name if agent else "Agent"
                        manager.agent_load[user_id] = manager.agent_load.get(user_id, 0) + 1
                        # Notify visitor
                        await manager.send_visitor(session_key, {
                            "type": "agent_join",
                            "agent_name": agent_name,
                            "timestamp": _ts(),
                        })
                        # Confirm to agent
                        await websocket.send_text(json.dumps({
                            "type": "session_update",
                            "session": _session_summary(sess, ""),
                        }))
                        await db.commit()

                # ── Agent sends message to visitor ────────────────────────────
                elif msg_type == "message":
                    session_key = msg.get("session_id", "")
                    text = str(msg.get("text", "")).strip()
                    if session_key and text:
                        await manager.send_visitor(session_key, {
                            "type": "message",
                            "from": "agent",
                            "text": text,
                            "timestamp": _ts(),
                        })
                        # Persist agent message to transcript
                        sess_res = await db.execute(select(Interaction).where(Interaction.session_key == session_key))
                        msg_sess = sess_res.scalar_one_or_none()
                        if msg_sess:
                            _log_msg(msg_sess, "agent", text)
                            await db.commit()

                # ── Agent releases session back to queue ──────────────────────
                elif msg_type == "release":
                    session_key = msg.get("session_id", "")
                    res3 = await db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    sess = res3.scalar_one_or_none()
                    if sess:
                        manager.agent_load[user_id] = max(0, manager.agent_load.get(user_id, 1) - 1)
                        sess.agent_id = None
                        sess.status = "waiting_agent"
                        await db.flush()
                        await manager.send_visitor(session_key, {
                            "type": "queue",
                            "message": "Agent has released the session. Waiting for next available agent.",
                            "timestamp": _ts(),
                        })
                        await db.commit()

                # ── Agent closes session ──────────────────────────────────────
                elif msg_type == "close":
                    session_key = msg.get("session_id", "")
                    res4 = await db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    sess = res4.scalar_one_or_none()
                    if sess:
                        if sess.agent_id and str(sess.agent_id) == user_id:
                            manager.agent_load[user_id] = max(0, manager.agent_load.get(user_id, 1) - 1)
                        sess.status = "closed"
                        await db.flush()
                        await manager.send_visitor(session_key, {
                            "type": "end",
                            "status": "closed_by_agent",
                            "message": "The agent has ended the session.",
                            "timestamp": _ts(),
                        })
                        await db.commit()
                        await websocket.send_text(json.dumps({
                            "type": "session_closed",
                            "session_id": session_key,
                        }))

                # ── Agent sets active campaign (for dispatch filtering) ─────────
                elif msg_type == "set_campaign":
                    campaign_id = msg.get("campaign_id")  # None = serve all
                    manager.agent_campaigns[user_id] = str(campaign_id) if campaign_id else None
                    await websocket.send_text(json.dumps({
                        "type": "campaign_set",
                        "campaign_id": campaign_id,
                    }))
                    # Auto-assign any waiting sessions for this campaign
                    if campaign_id:
                        waiting_res = await db.execute(
                            select(Interaction).where(Interaction.status == "waiting_agent")
                        )
                        for w_sess in waiting_res.scalars().all():
                            if not w_sess.queue_id:
                                continue
                            q_res = await db.execute(select(Queue).where(Queue.id == w_sess.queue_id))
                            q_obj = q_res.scalar_one_or_none()
                            if q_obj and q_obj.campaign_id and str(q_obj.campaign_id) == str(campaign_id):
                                assigned = await _auto_assign_session(w_sess, db)
                                if assigned:
                                    await db.commit()
                                    break  # one at a time

                # ── Agent sets their availability status ──────────────────────
                elif msg_type == "set_availability":
                    new_status = str(msg.get("status", "available")).lower()
                    VALID_STATUSES = {"available", "admin", "lunch", "break", "training", "meeting", "offline"}
                    if new_status not in VALID_STATUSES:
                        new_status = "available"
                    manager.agent_availability[user_id] = new_status
                    await websocket.send_text(json.dumps({
                        "type": "availability_set",
                        "status": new_status,
                    }))
                    _log.info("Agent %s availability -> %s", user_id, new_status)

                    # When going Available, sweep waiting sessions and assign
                    # up to the agent's max_concurrent_chats limit
                    if new_status == "available":
                        # Use a fresh DB session for the sweep so the long-lived agent WS
                        # session's stale transaction doesn't hide recently-committed sessions.
                        async with async_session() as sweep_db:
                            try:
                                agent_res = await sweep_db.execute(select(User).where(User.id == _uuid_mod.UUID(user_id)))
                                agent_obj = agent_res.scalar_one_or_none()
                                max_chats = (agent_obj.max_concurrent_chats or 5) if agent_obj else 5
                                current_load = manager.agent_load.get(user_id, 0)
                                slots = max_chats - current_load
                                _log.info("Availability sweep for %s: max=%s load=%s slots=%s", user_id, max_chats, current_load, slots)

                                if slots > 0:
                                    member_res = await sweep_db.execute(
                                        select(queue_agents.c.queue_id)
                                        .where(queue_agents.c.user_id == _uuid_mod.UUID(user_id))
                                    )
                                    agent_queue_ids = {str(r[0]) for r in member_res.all()}
                                    agent_camp = manager.agent_campaigns.get(user_id)

                                    waiting_res = await sweep_db.execute(
                                        select(Interaction)
                                        .where(Interaction.status == "waiting_agent")
                                        .order_by(Interaction.created_at.asc())
                                    )
                                    waiting_sessions = list(waiting_res.scalars().all())
                                    _log.info("Sweep found %d waiting sessions for agent %s", len(waiting_sessions), user_id)

                                    # Sort: queue members first
                                    waiting_sessions.sort(key=lambda s: 0 if (s.queue_id and str(s.queue_id) in agent_queue_ids) else 1)

                                    # Collect assignments — flush each but commit ONCE at end
                                    # (committing inside loop expires subsequent ORM instances in async SA)
                                    assignments: list = []  # [(sess_key, sess_summary)]
                                    agent_name = agent_obj.full_name if agent_obj else "Agent"

                                    for w_sess in waiting_sessions:
                                        if len(assignments) >= slots:
                                            break

                                        # Snapshot identity fields NOW (before any potential expiry)
                                        sess_key = w_sess.session_key
                                        sess_queue_id_str = str(w_sess.queue_id) if w_sess.queue_id else None
                                        sess_queue_uuid = w_sess.queue_id

                                        # Filter by scope
                                        if sess_queue_id_str and agent_queue_ids and sess_queue_id_str not in agent_queue_ids:
                                            if agent_camp is not None:
                                                q_res = await sweep_db.execute(select(Queue).where(Queue.id == sess_queue_uuid))
                                                q_obj = q_res.scalar_one_or_none()
                                                if not (q_obj and q_obj.campaign_id and str(q_obj.campaign_id) == agent_camp):
                                                    _log.info("Sweep skip %s (campaign mismatch)", sess_key)
                                                    continue

                                        w_sess.agent_id = _uuid_mod.UUID(user_id)
                                        w_sess.status = "with_agent"
                                        await sweep_db.flush()  # write but don't commit yet
                                        manager.agent_load[user_id] = manager.agent_load.get(user_id, 0) + 1
                                        assignments.append((sess_key, _session_summary(w_sess, "")))

                                    # Single commit for all assignments at once
                                    if assignments:
                                        await sweep_db.commit()
                                        for sess_key, sess_summary in assignments:
                                            await manager.send_visitor(sess_key, {
                                                "type": "agent_join",
                                                "agent_name": agent_name,
                                                "timestamp": _ts(),
                                            })
                                            await manager.send_agent(user_id, {
                                                "type": "session_assigned",
                                                "session": sess_summary,
                                            })
                                            _log.info("Sweep assigned session %s to agent %s", sess_key, user_id)
                            except Exception as sweep_err:
                                _log.exception("Availability sweep error for agent %s: %s", user_id, sweep_err)

                # ── Agent requests typing notification to visitor ──────────────
                elif msg_type == "typing":
                    session_key = msg.get("session_id", "")
                    await manager.send_visitor(session_key, {
                        "type": "typing",
                        "from": "agent",
                    })

        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect_agent(user_id)
