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
import base64
import logging
import shutil
import uuid as _file_uuid
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.database import async_session, get_db
from app.models import Connector, Interaction, FlowNode, FlowEdge, Flow, FlowNodeStats, FlowNodeVisitLog, User, Queue, Outcome, queue_agents, CampaignAttempt, Campaign, VoiceConnector
from app.config import get_settings
from app.auth import get_current_user
from app.routers.flows import (
    _resolve_template, _apply_set_variable, _evaluate_condition, _resolve_path, _set_path,
)

router = APIRouter(tags=["chat"])
_settings = get_settings()
_log = logging.getLogger("chat_ws")

# Default seconds an agent has to complete wrap-up after the visitor leaves.
WRAP_UP_TIMEOUT_SECS = 120
UPLOADS_DIR = Path("static/uploads/chat")

# ── Capacity helpers ──────────────────────────────────────────────────────────

def _get_effective_caps(user: User) -> dict:
    """Return the agent's effective capacity limits, merging global defaults.

    Returns a dict with keys:
        omni, voice, chat, whatsapp, email, sms
    """
    from app.routers.settings import SETTINGS_DEFAULTS

    def _g(key: str, fallback: int) -> int:
        return int(SETTINGS_DEFAULTS.get(key, fallback))

    def _eff(agent_val, default: int) -> int:
        return agent_val if agent_val is not None else default

    return {
        "omni":      _eff(user.omni_max,            _g("default_omni_max", 8)),
        "voice":     _eff(user.channel_max_voice,    _g("default_channel_max_voice", 1)),
        "chat":      _eff(user.channel_max_chat,     _g("default_channel_max_chat", 5)),
        "whatsapp":  _eff(user.channel_max_whatsapp, _g("default_channel_max_whatsapp", 3)),
        "email":     _eff(user.channel_max_email,    _g("default_channel_max_email", 5)),
        "sms":       _eff(user.channel_max_sms,      _g("default_channel_max_sms", 5)),
    }


def _channel_load(user_id: str, manager, channel: str) -> int:
    """Count the agent's current load for a specific channel type.

    Falls back to total load when per-channel tracking is not yet active.
    """
    ch_load = manager.agent_channel_load.get(user_id, {})
    return ch_load.get(channel, 0)


def _at_cap(caps: dict, user_id: str, manager, channel: str, override_active: bool) -> bool:
    """Return True if the agent is at or over the relevant capacity limits.

    Checks both the channel-specific cap and the omni total cap.
    When *override_active* is True the omni cap is treated as +1 (pick-next).
    """
    omni_limit   = caps["omni"] + (1 if override_active else 0)
    chan_limit    = caps.get(channel, caps["omni"])  # fall back to omni when no channel entry
    total_load   = manager.agent_load.get(user_id, 0)
    channel_load = _channel_load(user_id, manager, channel)

    if total_load >= omni_limit:
        return True
    if channel_load >= chan_limit:
        return True
    return False


async def _push_capacity_update(user_id: str, manager) -> None:
    """Send a capacity_update WS message to the agent with their current live load."""
    load = manager.agent_load.get(user_id, 0)
    ch   = manager.agent_channel_load.get(user_id, {})
    await manager.send_agent(user_id, {
        "type": "capacity_update",
        "load": {
            "total":     load,
            "voice":     ch.get("voice",     0),
            "chat":      ch.get("chat",      0),
            "whatsapp":  ch.get("whatsapp",  0),
            "email":     ch.get("email",     0),
            "sms":       ch.get("sms",       0),
        },
    })


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _settings.secret_key, algorithms=[_settings.algorithm])
    except JWTError:
        return None


# ─── Twilio REST helpers (voice call controls) ───────────────────────────────

async def _twilio_call_action(account_sid: str, auth_token: str, call_sid: str) -> bool:
    """End a Twilio call by transitioning its status to 'completed'."""
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json",
                data={"Status": "completed"},
                headers={"Authorization": f"Basic {creds}"},
            )
        return r.status_code in (200, 201)
    except Exception as _e:
        _log.warning("_twilio_call_action error: %s", _e)
        return False


async def _twilio_conference_participant(
    account_sid: str, auth_token: str, conference_name: str, call_sid: str, **kwargs
) -> bool:
    """Update a Twilio conference participant (Hold / Muted etc.)."""
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Conferences.json",
                params={"FriendlyName": conference_name, "Status": "in-progress"},
                headers=headers,
            )
            if r.status_code != 200:
                return False
            confs = r.json().get("conferences", [])
            if not confs:
                return False
            conf_sid = confs[0]["sid"]
            r2 = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                f"/Conferences/{conf_sid}/Participants/{call_sid}.json",
                data=kwargs,
                headers=headers,
            )
        return r2.status_code in (200, 201)
    except Exception as _e:
        _log.warning("_twilio_conference_participant error: %s", _e)
        return False


async def _twilio_warm_transfer(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    twiml_url: str,
) -> str | None:
    """Dial a third party into the existing conference room for a warm transfer.

    Uses the Twilio REST API to place a new outbound call whose TwiML URL
    instructs Twilio to join the transfer target into the named conference.
    Returns the new call SID on success, or None on failure.

    Args:
        account_sid: Twilio account SID.
        auth_token:  Twilio auth token.
        from_number: Caller ID shown to the transfer target (usually the campaign outbound number).
        to_number:   Phone number to dial in E.164 format (e.g. ``+27821234567``).
        twiml_url:   Publicly reachable URL that returns TwiML joining the conference.
    """
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json",
                data={
                    "To":   to_number,
                    "From": from_number,
                    "Url":  twiml_url,
                    "StatusCallbackMethod": "POST",
                },
                headers={"Authorization": f"Basic {creds}"},
            )
        if r.status_code in (200, 201):
            sid = r.json().get("sid", "")
            _log.info("warm_transfer: dialled %s → call SID %s", to_number, sid)
            return sid
        _log.warning("warm_transfer: Twilio returned %s — %s", r.status_code, r.text[:200])
        return None
    except Exception as exc:
        _log.warning("warm_transfer error: %s", exc)
        return None


async def _twilio_mute_agent_participant(
    account_sid: str, auth_token: str, conference_name: str, contact_call_sid: str, muted: bool
) -> bool:
    """Mute or unmute the agent's conference leg (all participants except the contact)."""
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Conferences.json",
                params={"FriendlyName": conference_name, "Status": "in-progress"},
                headers=headers,
            )
            if r.status_code != 200:
                return False
            confs = r.json().get("conferences", [])
            if not confs:
                return False
            conf_sid = confs[0]["sid"]
            r2 = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                f"/Conferences/{conf_sid}/Participants.json",
                headers=headers,
            )
            if r2.status_code != 200:
                return False
            muted_str = "true" if muted else "false"
            ok = True
            for p in r2.json().get("participants", []):
                if p.get("call_sid") != contact_call_sid:
                    r3 = await client.post(
                        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                        f"/Conferences/{conf_sid}/Participants/{p['call_sid']}.json",
                        data={"Muted": muted_str},
                        headers=headers,
                    )
                    if r3.status_code not in (200, 201):
                        ok = False
        return ok
    except Exception as _e:
        _log.warning("_twilio_mute_agent_participant error: %s", _e)
        return False


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
        # user_id → total active session count (for least-busy dispatch)
        self.agent_load: Dict[str, int] = {}
        # user_id → {channel: count}  — per-channel load tracking
        self.agent_channel_load: Dict[str, Dict[str, int]] = {}
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
        self.agent_channel_load.setdefault(user_id, {})
        self.agent_campaigns.setdefault(user_id, None)
        self.agent_availability.setdefault(user_id, "offline")

    def disconnect_agent(self, user_id: str):
        self.agents.pop(user_id, None)
        self.agent_load.pop(user_id, None)
        self.agent_channel_load.pop(user_id, None)
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
    queue_id: Optional[str], db: AsyncSession,
    preferred_language: Optional[str] = None,
) -> Optional[str]:
    """
    Find the least-busy online agent for a given queue.
    Priority tiers (within each tier, language-matched agents are preferred):
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

    # Build language-matched agent set for soft language preference routing
    lang_matched: set = set()
    if preferred_language:
        try:
            uuid_list = [_uuid_mod.UUID(uid) for uid in online_ids]
        except ValueError:
            uuid_list = []
        if uuid_list:
            lr = await db.execute(
                select(User.id, User.languages).where(User.id.in_(uuid_list))
            )
            lang_map = {str(r[0]): (r[1] or []) for r in lr.all()}
            lang_matched = {
                uid for uid in online_ids
                if preferred_language in lang_map.get(uid, [])
            }

    def _with_lang_pref(candidates: set) -> set:
        """Return language-matched subset if any; otherwise the full candidate set."""
        preferred = candidates & lang_matched
        return preferred if preferred else candidates

    campaign_id_str: Optional[str] = None

    if queue_id:
        try:
            q_uuid = _uuid_mod.UUID(queue_id)
        except ValueError:
            q_uuid = None

        if q_uuid:
            # 1. Queue-member agents that are online (prefer language-matched)
            res = await db.execute(
                select(queue_agents.c.user_id)
                .where(queue_agents.c.queue_id == q_uuid)
            )
            member_ids = {str(r[0]) for r in res.all()}
            available = member_ids & online_ids
            if available:
                return least_busy(_with_lang_pref(available))

            # Fetch campaign_id from the queue
            q_res = await db.execute(select(Queue).where(Queue.id == q_uuid))
            q_obj = q_res.scalar_one_or_none()
            if q_obj and q_obj.campaign_id:
                campaign_id_str = str(q_obj.campaign_id)

    # 2. Agents whose campaign preference matches (prefer language-matched)
    if campaign_id_str:
        campaign_agents = {
            uid for uid, cid in manager.agent_campaigns.items()
            if cid == campaign_id_str and uid in online_ids
        }
        if campaign_agents:
            return least_busy(_with_lang_pref(campaign_agents))

    # 3. Any online agent (fallback, prefer language-matched)
    return least_busy(_with_lang_pref(online_ids))


async def _auto_assign_session(
    session: Interaction, db: AsyncSession
) -> bool:
    """
    Try to auto-assign a waiting session to an available agent.
    Returns True if an agent was assigned.
    """
    queue_id_str = str(session.queue_id) if session.queue_id else None
    # Extract contact language (set by Translate node) for language-matched routing
    _flow_ctx = session.flow_context or {}
    preferred_language = (
        _flow_ctx.get("contact", {}).get("language")
        if isinstance(_flow_ctx, dict) else None
    )
    agent_uid = await _find_available_agent(queue_id_str, db, preferred_language=preferred_language)
    if not agent_uid:
        return False

    session.agent_id = _uuid_mod.UUID(agent_uid)
    # Segment: close queue wait, open agent handling phase
    _close_segment(session, "queue")
    _open_segment(session, "agent", agent_id=agent_uid)
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


def apply_outcome_to_session(
    sess: Interaction,
    outcome: Optional["Outcome"],
    agent_load: dict,
    user_id: str,
) -> tuple:
    """Apply a selected outcome to an interaction (pure logic, no DB/WS side-effects).

    Returns ``(action, outcome_code)`` where *action* is one of:
      - ``"end"``      — session was closed
      - ``"redirect"`` — session was reset to active and pointed at a new flow

    The caller is responsible for flushing/committing the DB session and
    sending the appropriate WebSocket messages.
    """
    action_type   = outcome.action_type if outcome else "end_interaction"
    outcome_code  = outcome.code        if outcome else "resolve"

    # Record wrap time if the session was in wrap-up
    if sess.wrap_started_at:
        delta = datetime.utcnow() - sess.wrap_started_at
        sess.wrap_time = max(0, int(delta.total_seconds()))

    if action_type == "end_interaction" or not outcome:
        if sess.agent_id and str(sess.agent_id) == user_id:
            agent_load[user_id] = max(0, agent_load.get(user_id, 1) - 1)
        _close_segment(sess, "agent")  # close agent segment on normal end
        sess.status             = "closed"
        sess.disconnect_outcome = outcome_code
        return ("end", outcome_code)

    if action_type == "flow_redirect" and outcome.redirect_flow_id:
        if sess.agent_id and str(sess.agent_id) == user_id:
            agent_load[user_id] = max(0, agent_load.get(user_id, 1) - 1)
        _close_segment(sess, "agent")  # close agent segment before re-entering flow
        _open_segment(sess, "flow", flow_id=str(outcome.redirect_flow_id))  # new flow segment
        sess.agent_id       = None
        sess.status         = "active"
        sess.waiting_node_id = None
        sess.disconnect_outcome = outcome_code
        ctx = dict(sess.flow_context or {})
        ctx["_current_flow_id"] = str(outcome.redirect_flow_id)
        sess.flow_context = ctx
        return ("redirect", outcome_code)

    # Fallback: treat unexpected combinations as end_interaction
    sess.status             = "closed"
    sess.disconnect_outcome = outcome_code
    return ("end", outcome_code)


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
        "last_activity_at": (session.last_activity_at.isoformat() if session.last_activity_at else None),
        "agent_id": str(session.agent_id) if session.agent_id else None,
        "notes": session.notes,
        "message_log": list(session.message_log or []),
        "segments": list(session.segments or []),
    }


# ─── Segment lifecycle helpers ────────────────────────────────────────────────
# Each segment = a logical phase: flow | queue | agent
# Stored as JSONB array on Interaction.segments — one entry per phase.
# Segment shape:
#   {type, started_at, ended_at, summary,
#    agent_id?, queue_id?, flow_id?, waited_seconds?}
# ─────────────────────────────────────────────────────────────────────────────

def _seg_now() -> str:
    return datetime.utcnow().isoformat()


def _open_segment(sess: "Interaction", seg_type: str, **extra) -> None:
    """Append a new open segment of the given type."""
    segs: list = list(sess.segments or [])
    segs.append({"type": seg_type, "started_at": _seg_now(), "ended_at": None, "summary": None, **extra})
    sess.segments = segs


def _close_segment(sess: "Interaction", seg_type: str | None = None) -> None:
    """Close the most recent open segment (optionally filtered by type)."""
    segs: list = list(sess.segments or [])
    for seg in reversed(segs):
        if seg.get("ended_at") is None:
            if seg_type is None or seg.get("type") == seg_type:
                seg["ended_at"] = _seg_now()
                break
    sess.segments = segs


def _get_last_open_segment(sess: "Interaction", seg_type: str | None = None) -> "dict | None":
    for seg in reversed(list(sess.segments or [])):
        if seg.get("ended_at") is None:
            if seg_type is None or seg.get("type") == seg_type:
                return seg
    return None


# ─── Per-segment summarisation ────────────────────────────────────────────────

async def _summarise_segment_async(session_key: str) -> None:
    """
    Fire-and-forget: summarise only the agent-segment messages for this session,
    write to segments[-1].summary and pre-fill Interaction.notes for the wrap panel.
    Called immediately on wrap_up so the agent sees the summary while still in wrap-up.
    """
    try:
        async with async_session() as db:
            res = await db.execute(
                select(Interaction).where(Interaction.session_key == session_key)
            )
            sess = res.scalar_one_or_none()
            if not sess or not sess.message_log:
                return

            # Find the most recently started agent segment to bound the messages
            segs: list = list(sess.segments or [])
            agent_seg = next(
                (s for s in reversed(segs) if s.get("type") == "agent"),
                None,
            )
            seg_start_iso: str | None = agent_seg.get("started_at") if agent_seg else None

            # Filter to messages within the agent segment (or all if no boundary)
            lines = []
            for e in sess.message_log:
                role = e.get("from", "?")
                text = (e.get("text") or "").strip()
                if not text or e.get("subtype") == "attachment":
                    continue
                if seg_start_iso:
                    ts = e.get("ts", "")
                    if ts and ts < seg_start_iso:
                        continue
                lines.append(f"{role}: {text}")

            if not lines:
                return

            transcript = "\n".join(lines)

            async with httpx.AsyncClient(timeout=90.0) as hc:
                r = await hc.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen3:8b",
                        "stream": False,
                        "options": {"num_ctx": 4096, "think": False},
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a concise contact-centre analyst. "
                                    "Summarise only the AGENT conversation segment below in 3–4 bullet points. "
                                    "Cover: issue raised, what the agent did, outcome or next steps, "
                                    "and any follow-up required. "
                                    "Be factual. No filler phrases."
                                ),
                            },
                            {"role": "user", "content": transcript},
                        ],
                    },
                )
            data = r.json()
            summary = ((data.get("message") or {}).get("content") or "").strip()
            if not summary:
                return

            # Reload inside the same session to update safely
            res2 = await db.execute(
                select(Interaction).where(Interaction.session_key == session_key)
            )
            sess2 = res2.scalar_one_or_none()
            if not sess2:
                return

            segs2: list = list(sess2.segments or [])
            # Write to the last agent segment's summary
            for seg in reversed(segs2):
                if seg.get("type") == "agent":
                    seg["summary"] = summary
                    break
            sess2.segments = segs2

            # Pre-fill notes for the wrap panel — only if not already set by a previous close
            if not sess2.notes:
                sess2.notes = summary

            await db.commit()

            # Push to agent panel so the summary appears immediately
            await manager.broadcast_to_agents({
                "type": "session_summary",
                "session_id": session_key,
                "notes": summary,
                "source": "wrap_up",
            })
    except Exception as exc:
        _log.warning("_summarise_segment_async failed for %s: %s", session_key, exc)


async def _fire_chat_ended_event(
    session_key: str,
    connector_id: Optional[str],
    closed_by: str,
    channel: str = "chat",
    contact_id: Optional[str] = None,
    queue_id: Optional[str] = None,
) -> None:
    """Fire POST /api/v1/inbound/chat-ended at localhost to trigger start_chat_ended flows."""
    import httpx
    try:
        payload = {
            "session_key": session_key,
            "connector_id": connector_id,
            "closed_by": closed_by,
            "channel": channel,
            "contact_id": contact_id,
            "queue_id": queue_id,
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post("http://127.0.0.1:8092/api/v1/inbound/chat-ended", json=payload)
    except Exception as exc:
        _log.warning("_fire_chat_ended_event: could not notify inbound router: %s", exc)


async def _dispatch_conversation_event(session_key: str, topic: str, closed_by: str = "unknown") -> None:
    """Fire a Routines event for a conversation state change (fire-and-forget)."""
    try:
        from app.services.event_dispatcher import dispatch
        async with async_session() as db:
            res = await db.execute(
                select(Interaction).where(Interaction.session_key == session_key)
            )
            sess = res.scalar_one_or_none()
            if not sess:
                return
            vm = sess.visitor_metadata or {}
            event_data = {
                "event":        topic,
                "id":           str(sess.id),
                "session_key":  session_key,
                "channel":      vm.get("channel", "chat"),
                "status":       sess.status,
                "closed_by":    closed_by,
                "contact_id":   str(sess.contact_id) if sess.contact_id else None,
                "queue_id":     str(sess.queue_id) if sess.queue_id else None,
                "connector_id": str(sess.connector_id) if sess.connector_id else None,
                "assigned_to":  str(sess.assigned_to) if getattr(sess, "assigned_to", None) else None,
                "ended_at":     sess.ended_at.isoformat() + "Z" if sess.ended_at else None,
            }
            await dispatch(topic, event_data, db)
    except Exception as exc:
        _log.warning("_dispatch_conversation_event failed topic=%s session=%s: %s", topic, session_key, exc)


async def _summarise_async(session_key: str) -> None:
    """
    Fire-and-forget: produce a final roll-up summary on close.
    If segment summaries already exist, concatenate them (cheap).
    Falls back to full-transcript LLM call if no segments exist.
    """
    try:
        async with async_session() as db:
            res = await db.execute(
                select(Interaction).where(Interaction.session_key == session_key)
            )
            sess = res.scalar_one_or_none()
            if not sess:
                return

            segs: list = list(sess.segments or [])
            segment_summaries = [
                s["summary"] for s in segs
                if s.get("summary") and s.get("type") == "agent"
            ]

            # ── Fast path: roll-up from already-computed segment summaries ──────
            if segment_summaries:
                if len(segment_summaries) == 1:
                    # Only one agent segment — the segment summary IS the final summary
                    rollup = segment_summaries[0]
                else:
                    # Multiple handoffs — concatenate with headers
                    parts = []
                    agent_idx = 0
                    for s in segs:
                        if s.get("type") == "agent" and s.get("summary"):
                            agent_idx += 1
                            parts.append(f"**Agent segment {agent_idx}:**\n{s['summary']}")
                    rollup = "\n\n".join(parts)
                sess.notes = rollup
                await db.commit()
                await manager.broadcast_to_agents({
                    "type": "session_summary",
                    "session_id": session_key,
                    "notes": rollup,
                    "source": "close_rollup",
                })
                return

            # ── Fallback: full-transcript LLM summarisation ──────────────────
            if not sess.message_log:
                return
            lines = []
            for e in sess.message_log:
                role = e.get("from", "?")
                text = (e.get("text") or "").strip()
                if text and e.get("subtype") not in ("attachment",):
                    lines.append(f"{role}: {text}")
            if not lines:
                return
            transcript = "\n".join(lines)
            async with httpx.AsyncClient(timeout=90.0) as hc:
                r = await hc.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen3:8b",
                        "stream": False,
                        "options": {"num_ctx": 4096, "think": False},
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a concise support analyst. "
                                    "Summarise the following conversation in 3–5 bullet points. "
                                    "Cover: issue raised, steps taken, outcome/resolution, "
                                    "and any follow-up required. "
                                    "Be factual and brief — no padding or filler phrases."
                                ),
                            },
                            {"role": "user", "content": transcript},
                        ],
                    },
                )
            data = r.json()
            summary = ((data.get("message") or {}).get("content") or "").strip()
            if not summary:
                return
            # Back-fill the summary into the last agent segment for QA/AI feeds
            segs_fb: list = list(sess.segments or [])
            for seg in reversed(segs_fb):
                if seg.get("type") == "agent" and not seg.get("summary"):
                    seg["summary"] = summary
                    break
            sess.segments = segs_fb
            sess.notes = summary
            await db.commit()
            await manager.broadcast_to_agents({
                "type": "session_summary",
                "session_id": session_key,
                "notes": summary,
            })
    except Exception as exc:
        _log.warning("_summarise_async failed for %s: %s", session_key, exc)


async def _notify_wizzardqa(session_key: str) -> None:
    """Fire-and-forget: POST closed-interaction payload to WizzardQA webhook."""
    from app.config import get_settings as _get_settings
    _cfg = _get_settings()
    if not _cfg.wizzardqa_enabled:
        return
    try:
        async with async_session() as db:
            res = await db.execute(
                select(Interaction).where(Interaction.session_key == session_key)
            )
            sess = res.scalar_one_or_none()
            if not sess:
                return

            # Derive handling_type from lifecycle segments
            segs = list(sess.segments or [])
            seg_types = {s.get("type") for s in segs}
            if "agent" in seg_types and "flow" in seg_types:
                handling_type = "blended"
            elif "agent" in seg_types:
                handling_type = "human"
            elif "flow" in seg_types:
                handling_type = "flow"
            else:
                handling_type = "bot_only" if not sess.agent_id else "human"

            payload = {
                "interaction_id":     str(sess.id),
                "session_key":        sess.session_key,
                "connector_id":       str(sess.connector_id) if sess.connector_id else None,
                "agent_id":           str(sess.agent_id)     if sess.agent_id     else None,
                "contact_id":         str(sess.contact_id)   if sess.contact_id   else None,
                "message_log":        list(sess.message_log or []),
                "disconnect_outcome": sess.disconnect_outcome or sess.status,
                "notes":              sess.notes or "",
                "csat_score":         sess.csat_score,
                "csat_comment":       sess.csat_comment,
                "nps_score":          sess.nps_score,
                "nps_reason":         sess.nps_reason,
                "direction":          sess.direction,
                "channel":            sess.channel,
                "handling_type":      handling_type,
                "source_system":      "wizzardchat",
                "segments":           segs,
                "created_at":         sess.created_at.isoformat() if sess.created_at else None,
                "last_activity_at":   sess.last_activity_at.isoformat() if sess.last_activity_at else None,
            }
        headers = {"Content-Type": "application/json"}
        if _cfg.wizzardqa_integration_key:
            headers["X-WizzardQA-Key"] = _cfg.wizzardqa_integration_key
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(_cfg.wizzardqa_webhook_url, json=payload, headers=headers)
    except Exception as exc:
        _log.debug("_notify_wizzardqa failed for %s: %s", session_key, exc)


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


async def _record_node_visit(flow_id: str, node: FlowNode, db: AsyncSession,
                              from_node_id: Optional[str] = None,
                              event_type: str = 'visit') -> None:
    """Upsert a cumulative counter (visits only) + append a visit-log row.

    event_type values: 'visit' (normal traversal), 'error' (exception during
    node execution), 'abandon' (visitor disconnected while at this node).
    """
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        now = datetime.utcnow()
        if event_type == 'visit':
            # ── Cumulative counter (visits only) ──
            stmt = (
                _pg_insert(FlowNodeStats)
                .values(
                    id=_file_uuid.uuid4(),
                    flow_id=flow_id,
                    node_id=node.id,
                    node_label=node.label or "",
                    node_type=node.node_type,
                    visit_count=1,
                    last_visited_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_flow_node_stats",
                    set_={
                        "visit_count": FlowNodeStats.visit_count + 1,
                        "last_visited_at": now,
                    },
                )
            )
            await db.execute(stmt)
        # ── Append-only log for time-windowed + per-edge + error/abandon analytics ──
        await db.execute(
            _pg_insert(FlowNodeVisitLog).values(
                id=_file_uuid.uuid4(),
                flow_id=flow_id,
                node_id=node.id,
                node_label=node.label or "",
                node_type=node.node_type,
                from_node_id=from_node_id,
                event_type=event_type,
                visited_at=now,
            )
        )
    except Exception:
        pass  # stats are best-effort; never break flow execution


async def _record_event_by_node_id(
    flow_id: str,
    node_id: str,
    db: AsyncSession,
    event_type: str,
) -> None:
    """Record an error or abandon event when only the node UUID is available.

    Looks up node label/type from FlowNode then writes a FlowNodeVisitLog row.
    Used by outer exception handlers and the disconnect sweep.
    """
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        node_res = await db.execute(
            select(FlowNode).where(FlowNode.id == _uuid_mod.UUID(str(node_id)))
        )
        node = node_res.scalar_one_or_none()
        if not node:
            return
        await db.execute(
            _pg_insert(FlowNodeVisitLog).values(
                id=_file_uuid.uuid4(),
                flow_id=flow_id,
                node_id=node.id,
                node_label=node.label or "",
                node_type=node.node_type,
                from_node_id=None,
                event_type=event_type,
                visited_at=datetime.utcnow(),
            )
        )
    except Exception:
        pass


# ── Survey-variable auto-save ────────────────────────────────────────────────
# Any flow (including sub-flows) that sets these well-known context variables
# will have the values persisted to the interaction record automatically when
# the flow's `end` node fires.  No http_request node or custom API calls needed.
#
# Supported variables:
#   csat_score     int  1–5   → interactions.csat_score  (+ csat_submitted_at)
#   csat_comment   str        → interactions.csat_comment
#   nps_score      int  0–10  → interactions.nps_score   (+ nps_submitted_at)
#   nps_reason     str        → interactions.nps_reason
# ─────────────────────────────────────────────────────────────────────────────

_SURVEY_VARS = {
    "csat_score":   ("csat_score",   int,  (1, 5),    "csat_submitted_at"),
    "nps_score":    ("nps_score",    int,  (0, 10),   "nps_submitted_at"),
}
_SURVEY_TEXT_VARS = {
    "csat_comment": "csat_comment",
    "nps_reason":   "nps_reason",
}


async def _save_survey_vars(session: Interaction, ctx: dict, db: AsyncSession) -> None:
    """Persist well-known survey variables from flow context to the interaction."""
    changed = False
    now = datetime.utcnow()

    for ctx_key, (col, coerce, (lo, hi), ts_col) in _SURVEY_VARS.items():
        raw = ctx.get(ctx_key)
        if raw is None:
            continue
        try:
            val = coerce(str(raw).strip().split(".")[0])
        except (ValueError, TypeError):
            continue
        if not (lo <= val <= hi):
            continue
        if getattr(session, col) != val:
            setattr(session, col, val)
            setattr(session, ts_col, now)
            changed = True

    for ctx_key, col in _SURVEY_TEXT_VARS.items():
        raw = ctx.get(ctx_key)
        if raw is None:
            continue
        val = str(raw).strip()
        if val.lower() in ("", "skip", "none", "null"):
            val = None
        if getattr(session, col) != val:
            setattr(session, col, val)
            changed = True

    if changed:
        await db.flush()
        _log.info(
            "_save_survey_vars: saved survey data for session %s",
            session.session_key,
        )


async def run_flow(
    session: Interaction,
    connector: Optional[Connector],
    db: AsyncSession,
    agent_ws: Optional[WebSocket] = None,
):
    """
    Execute the linked flow starting from:
    - The node AFTER the waiting node (if resuming)
    - The node AFTER the start node (if fresh)

    Execute the linked flow, pushing messages to the visitor's SSE queue.
    Pauses at input/queue nodes and persists state to DB.

    ``connector`` may be None when this is called via a flow-redirect outcome;
    in that case ``_current_flow_id`` must already be set in session.flow_context.

    ``agent_ws`` is the WebSocket of the agent who triggered this flow (e.g. via
    a flow-redirect outcome).  When provided, every bot/system message sent to the
    visitor is also mirrored to the agent so they can watch the conversation.
    """
    ctx: dict = dict(session.flow_context or {})

    # Always keep read-only system variables in ctx so nodes like http_request
    # can reference {{_session_key}} and {{_interaction_id}} in URL / body templates.
    ctx["_session_key"]      = str(session.session_key)
    ctx["_interaction_id"]   = str(session.id)

    # Outcome flow-redirect sets _current_flow_id before calling run_flow.
    # Fall back to the connector's default flow only when not set.
    _resume_flow_id = ctx.get("_current_flow_id") or (
        str(connector.flow_id) if (connector and connector.flow_id) else None
    )

    if not _resume_flow_id:
        await manager.send_visitor(session.session_key, {
            "type": "message", "from": "bot",
            "text": "This connector has no flow configured.", "timestamp": _ts(),
        })
        _log.warning("run_flow: no flow to run for session %s", session.session_key)
        return

    _log.info("run_flow: starting flow %s for session %s", _resume_flow_id, session.session_key)
    nodes, edges = await _load_flow_graph(_resume_flow_id, db)

    # Open a flow segment if none is currently open (fresh start or flow-redirect re-entry).
    # Resumes from waiting nodes (visitor replying) skip this — an open segment already exists.
    if _get_last_open_segment(session) is None:
        _open_segment(session, "flow", flow_id=_resume_flow_id)

    # Determine starting point
    # waiting_node_id is a UUID column — cast to str before comparing against
    # the str-keyed nodes dict (uuid.UUID in str-dict → always False otherwise)
    _wn_str = str(session.waiting_node_id) if session.waiting_node_id else None
    if _wn_str and _wn_str in nodes:
        _from_id: Optional[str] = _wn_str
        # ai_bot (multi-turn): re-execute the same node so it can process the
        # new visitor message.  All other waiting nodes (input, queue, etc.)
        # have already captured their value and should advance past themselves.
        _wn_node = nodes[_wn_str]
        _log.info("run_flow resume: waiting_node=%s type=%s",
                  _wn_str[:8], _wn_node.node_type)
        if _wn_node.node_type == "ai_bot":
            current_id = _wn_str           # always re-execute ai_bot (multi-turn)
            _log.info("run_flow: re-executing ai_bot node %s", _wn_str[:8])
        else:
            # Resolve which handle to follow (default or timeout)
            _timeout_node = ctx.pop("_input_timeout", None)
            if _timeout_node == _wn_str:
                # Follow timeout edge; fall back to default if not wired
                current_id = _next_node_id(edges, _wn_str, handle="timeout") or _next_node_id(edges, _wn_str)
            else:
                current_id = _next_node_id(edges, _wn_str)
        session.waiting_node_id = None
    else:
        start = next((n for n in nodes.values() if n.node_type == "start"), None)
        if not start:
            await manager.send_visitor(session.session_key, {
                "type": "error", "message": "Flow has no start node.", "timestamp": _ts(),
            })
            return
        # Count the start node itself so the heatmap shows entry traffic
        await _record_node_visit(_resume_flow_id, start, db, from_node_id=None)
        _from_id = str(start.id)
        current_id = _next_node_id(edges, str(start.id))

    async def send(data: dict) -> None:  # noqa: E306
        """Push to visitor SSE and, optionally, mirror to the triggering agent."""
        await manager.send_visitor(session.session_key, data)
        if agent_ws is not None:
            msg_type = data.get("type")
            try:
                if msg_type == "message":
                    mirror = {
                        "type": "message",
                        "session_id": session.session_key,
                        "from": data.get("from", "bot"),
                        "text": data.get("text", ""),
                        "timestamp": data.get("timestamp", _ts()),
                        "subtype": "message",
                    }
                    await agent_ws.send_text(json.dumps(mirror))
                elif msg_type == "menu":
                    opts = data.get("options", [])
                    opts_text = "  |  ".join(
                        f"{o.get('key', '?')}. {o.get('text', '')}" for o in opts
                    )
                    mirror = {
                        "type": "message",
                        "session_id": session.session_key,
                        "from": "bot",
                        "text": f"{data.get('text', '')}\n{opts_text}" if opts_text else data.get("text", ""),
                        "timestamp": data.get("timestamp", _ts()),
                        "subtype": "menu",
                    }
                    await agent_ws.send_text(json.dumps(mirror))
                elif msg_type == "end" and data.get("message"):
                    mirror = {
                        "type": "message",
                        "session_id": session.session_key,
                        "from": "system",
                        "text": data.get("message", ""),
                        "timestamp": data.get("timestamp", _ts()),
                        "subtype": "end",
                    }
                    await agent_ws.send_text(json.dumps(mirror))
            except Exception:
                pass  # agent WS gone — ignore, visitor delivery already done

    for _step in range(200):  # safety limit (sub-flows add extra steps)
        if not current_id or current_id not in nodes:
            break

        node = nodes[current_id]
        config: dict = node.config or {}

        # Track which node is executing so outer exception handlers can log errors
        ctx['_exec_node_id'] = current_id
        ctx['_exec_flow_id'] = str(_resume_flow_id)
        session.flow_context = ctx  # kept in sync so outer except can read _exec_node_id

        # Record visit for analytics (from_node_id tracks which edge was traversed)
        await _record_node_visit(_resume_flow_id, node, db, from_node_id=_from_id)
        _from_id = current_id  # next node's "from" is this node

        # ── End ──────────────────────────────────────────────────────────────
        if node.node_type == "end":
            # Persist any survey variables collected by this flow / sub-flow
            await _save_survey_vars(session, ctx, db)
            call_stack = ctx.get("_call_stack", [])
            if call_stack:
                # End of a sub-flow — pop back to parent and continue
                frame = call_stack.pop()
                parent_flow_id = frame["flow_id"]
                # Restore parent context snapshot
                parent_ctx: dict = dict(frame.get("parent_ctx") or {})
                # Export the sub-flow result back to parent
                result_var = frame.get("result_variable", "")
                output_var = frame.get("output_variable", "")
                if output_var:
                    # The sub-flow should have set result_variable (or "result" by convention)
                    lookup_key = result_var or "result"
                    parent_ctx[output_var] = ctx.get(lookup_key, ctx.get("result", ""))
                # Reinstate system keys
                parent_ctx["_call_stack"] = call_stack
                parent_ctx["_current_flow_id"] = parent_flow_id
                ctx = parent_ctx
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
            asyncio.create_task(_summarise_async(session.session_key))
            asyncio.create_task(_notify_wizzardqa(session.session_key))
            asyncio.create_task(_fire_chat_ended_event(
                session_key=session.session_key,
                connector_id=str(session.connector_id) if session.connector_id else None,
                closed_by="flow_end",
                channel=(session.visitor_metadata or {}).get("channel", "chat"),
                contact_id=str(session.contact_id) if getattr(session, "contact_id", None) else None,
                queue_id=str(session.queue_id) if session.queue_id else None,
            ))
            asyncio.create_task(_dispatch_conversation_event(session.session_key, "conversation.closed", "flow_end"))
            return

        # ── Message / Send Message ────────────────────────────────────────────
        elif node.node_type in ("message", "send_message"):
            # "text" is the standard config key; "message" is used by send_message nodes
            text = _resolve_template(config.get("text") or config.get("message", ""), ctx)
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

        # ── Save Survey ───────────────────────────────────────────────────────
        elif node.node_type == "save_survey":
            _s_name  = str(config.get("survey_name") or "").strip()
            _fields  = config.get("fields") or {}    # {field_name: ctx_variable, ...}
            if _s_name and isinstance(_fields, dict) and _fields:
                from app.models import SurveySubmission
                _now = datetime.utcnow()
                # Collect all non-empty responses from the flow context
                _responses: dict = {}
                for _fname, _cvar in _fields.items():
                    _fname = str(_fname).strip()
                    _cvar  = str(_cvar).strip()
                    if not _fname or not _cvar:
                        continue
                    _raw = ctx.get(_cvar)
                    if _raw is not None:
                        _sval = str(_raw).strip()
                        if _sval.lower() not in ("", "none", "null"):
                            _responses[_fname] = _sval
                # Write the survey_submissions row
                db.add(SurveySubmission(
                    interaction_id=session.id,
                    survey_name=_s_name,
                    responses=_responses,
                    submitted_at=_now,
                ))
                # Backwards-compat mirror: keep interactions.csat_*/nps_* columns in sync
                # so existing reporting queries continue to work without changes.
                _compat_score = {
                    "csat": ("score", int, (1, 5),   "csat_score",  "csat_submitted_at"),
                    "nps":  ("score", int, (0, 10),  "nps_score",   "nps_submitted_at"),
                }
                _compat_text = {
                    "csat": {"comment": "csat_comment"},
                    "nps":  {"reason":  "nps_reason", "comment": "nps_reason"},
                }
                if _s_name in _compat_score:
                    _score_field, _coerce, (_lo, _hi), _col, _tc = _compat_score[_s_name]
                    _score_raw = _responses.get(_score_field)
                    if _score_raw is not None:
                        try:
                            _score_val = _coerce(_score_raw.split(".")[0])
                            if _lo <= _score_val <= _hi:
                                setattr(session, _col, _score_val)
                                setattr(session, _tc, _now)
                        except (ValueError, TypeError):
                            pass
                    for _tf, _tcol in _compat_text.get(_s_name, {}).items():
                        _tv = _responses.get(_tf)
                        setattr(session, _tcol, _tv)  # None clears it, string sets it
                await db.flush()
                _log.info("save_survey: %s — %d field(s) for session %s",
                          _s_name, len(_responses), session.session_key)
            current_id = _next_node_id(edges, current_id)

        # ── Set Variable ──────────────────────────────────────────────────────
        elif node.node_type == "set_variable":
            ctx = _apply_set_variable(ctx, config)
            current_id = _next_node_id(edges, current_id)

        # ── Wait / Delay ───────────────────────────────────────────────────────
        elif node.node_type == "wait":
            duration = float(config.get("duration", 0) or 0)
            unit = str(config.get("unit", "seconds")).lower()
            if unit == "minutes":
                duration *= 60
            elif unit == "hours":
                duration *= 3600
            if duration > 0:
                # Suspend the flow — store resume timestamp; background sweep restarts it
                resume_at = datetime.utcnow() + timedelta(seconds=duration)
                ctx["_wait_resume_at"] = resume_at.isoformat()
                session.waiting_node_id = current_id
                session.flow_context = ctx
                await db.flush()
                return  # background _wait_resume_sweep will continue execution
            # duration == 0: pass-through immediately
            current_id = _next_node_id(edges, current_id)

        # ── Switch / multi-branch ─────────────────────────────────────────────
        elif node.node_type == "switch":
            cases = config.get("cases") or []
            chosen_handle = "default"
            for idx, case_def in enumerate(cases):
                # New format: case_def["conditions"] is a list of {variable, operator, value}
                # Legacy format (single condition on global variable): fall back gracefully
                conditions = case_def.get("conditions")
                if conditions:  # new multi-condition format
                    case_matched = all(
                        _evaluate_condition(ctx, {
                            "variable": cond.get("variable", ""),
                            "operator": cond.get("operator", "equals"),
                            "value": _resolve_template(str(cond.get("value", "")), ctx),
                        })
                        for cond in conditions if cond.get("variable")
                    ) if any(cond.get("variable") for cond in conditions) else False
                else:  # legacy single-condition
                    legacy_var = config.get("variable", "")
                    case_matched = _evaluate_condition(ctx, {
                        "variable": legacy_var,
                        "operator": case_def.get("operator", "equals"),
                        "value": _resolve_template(str(case_def.get("value", "")), ctx),
                    })
                if case_matched:
                    chosen_handle = f"case_{idx}"
                    break
            current_id = _next_node_id(edges, current_id, chosen_handle)

        # ── A/B Split ─────────────────────────────────────────────────────────
        elif node.node_type == "ab_split":
            import random as _random
            split_percent = float(config.get("split_percent", 50))
            tag_a = config.get("tag_a") or "branch_a"
            tag_b = config.get("tag_b") or "branch_b"
            if _random.random() * 100 < split_percent:
                ctx["_ab_variant"] = tag_a
                current_id = _next_node_id(edges, current_id, "branch_a")
            else:
                ctx["_ab_variant"] = tag_b
                current_id = _next_node_id(edges, current_id, "branch_b")

        # ── Loop ──────────────────────────────────────────────────────────────
        elif node.node_type == "loop":
            array_var = config.get("array_variable", "")
            item_var = config.get("item_variable", "item") or "item"
            index_var = config.get("index_variable", "loop_index") or "loop_index"
            max_iter = int(config.get("max_iterations", 50) or 50)
            state_key = f"_loop_{current_id}"
            arr = _resolve_path(ctx, array_var)
            if not isinstance(arr, list):
                ctx.pop(state_key, None)
                current_id = _next_node_id(edges, current_id, "done")
            else:
                idx = ctx.get(state_key, 0)
                if idx >= len(arr) or idx >= max_iter:
                    ctx.pop(state_key, None)
                    current_id = _next_node_id(edges, current_id, "done")
                else:
                    ctx[item_var] = arr[idx]
                    ctx[index_var] = idx
                    ctx[state_key] = idx + 1
                    current_id = _next_node_id(edges, current_id, "loop")

        # ── Time Gate ─────────────────────────────────────────────────────────
        elif node.node_type == "time_gate":
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _ZI
            tz_name = config.get("timezone", "Africa/Johannesburg") or "Africa/Johannesburg"
            try:
                _tz = _ZI(tz_name)
            except Exception:
                _tz = _ZI("Africa/Johannesburg")
            _now = _dt.now(_tz)
            _day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            _today = _day_map[_now.weekday()]
            _raw_days = config.get("days", "Mon,Tue,Wed,Thu,Fri") or "Mon,Tue,Wed,Thu,Fri"
            _allowed = [d.strip() for d in _raw_days.split(",") if d.strip()]
            try:
                _sh, _sm = (int(x) for x in config.get("start_time", "08:00").split(":"))
                _eh, _em = (int(x) for x in config.get("end_time", "17:00").split(":"))
                _now_m = _now.hour * 60 + _now.minute
                _is_open = _today in _allowed and (_sh * 60 + _sm) <= _now_m < (_eh * 60 + _em)
            except Exception:
                _is_open = False
            current_id = _next_node_id(edges, current_id, "open" if _is_open else "closed")

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

            # Segment: close any open flow segment, open a queue segment
            _close_segment(session)
            _open_segment(session, "queue",
                          queue_id=str(session.queue_id) if session.queue_id else None)
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
                return_node_id = _next_node_id(edges, current_id)
                call_stack = list(ctx.get("_call_stack") or [])

                # Build scoped sub-flow context — only mapped variables are passed in
                input_mapping = config.get("input_mapping") or {}
                if isinstance(input_mapping, str):
                    try:
                        input_mapping = json.loads(input_mapping)
                    except Exception:
                        input_mapping = {}
                sub_ctx: dict = {}
                for sub_var, parent_val in (input_mapping or {}).items():
                    if sub_var:
                        sub_ctx[sub_var] = _resolve_template(str(parent_val), ctx)

                # Push return frame with parent ctx snapshot
                call_stack.append({
                    "flow_id": str(_resume_flow_id),
                    "return_node_id": return_node_id,
                    "parent_ctx": {k: v for k, v in ctx.items() if not k.startswith("_")},
                    "result_variable": config.get("result_variable", ""),
                    "output_variable": config.get("output_variable", ""),
                })
                sub_ctx["_call_stack"] = call_stack
                sub_ctx["_current_flow_id"] = str(target_flow_id)
                ctx = sub_ctx
                _resume_flow_id = str(target_flow_id)
                nodes, edges = await _load_flow_graph(target_flow_id, db)
                sub_start = next((n for n in nodes.values() if n.node_type == "start"), None)
                if not sub_start:
                    # Sub-flow has no start — pop frame and restore parent
                    frame = call_stack.pop()
                    ctx = dict(frame.get("parent_ctx") or {})
                    ctx["_call_stack"] = call_stack
                    ctx["_current_flow_id"] = call_stack[-1]["flow_id"] if call_stack else str(connector.flow_id)
                    nodes, edges = await _load_flow_graph(ctx["_current_flow_id"], db)
                    _resume_flow_id = ctx["_current_flow_id"]
                    current_id = return_node_id
                else:
                    current_id = _next_node_id(edges, str(sub_start.id))

        # ── AI Bot ────────────────────────────────────────────────────────────────
        elif node.node_type == "ai_bot":
            ai_model     = config.get("model", "gpt-4o")
            sys_prompt   = _resolve_template(config.get("system_prompt", "You are a helpful assistant."), ctx)
            temperature  = float(config.get("temperature", 0.7) or 0.7)
            max_turns    = int(config.get("max_turns", 10) or 10)
            out_var      = config.get("output_variable", "")
            exit_kws     = [k.strip().lower() for k in (config.get("exit_keywords") or "").split(",") if k.strip()]

            # Conversation history persisted in flow context
            history = list(ctx.get("_aibot_history") or [])
            turns   = int(ctx.get("_aibot_turns") or 0)

            # Consume latest visitor message (set by handle_visitor_message on revisit)
            last_msg = ctx.pop("_aibot_last_msg", None)

            if last_msg is None and not history:
                # First entry: seed with the most recent visitor message from the log
                for entry in reversed(session.message_log or []):
                    if entry.get("from") == "visitor" and entry.get("text"):
                        last_msg = entry["text"]
                        break

            if last_msg:
                history.append({"role": "user", "content": last_msg})

            # Resolve model + provider
            if ai_model.startswith("wizzardai://"):
                _rest = ai_model[len("wizzardai://"):]
                _parts = _rest.split("/", 1)
                _provider = _parts[0] if len(_parts) == 2 else None
                _actual_model = _parts[1] if len(_parts) == 2 else _parts[0]
            else:
                _provider = None
                _actual_model = ai_model

            _wai_url  = _settings.wizzardai_base_url.rstrip("/")
            _wai_key  = _settings.wizzardai_api_key
            _wai_hdrs = {"X-WizzardAI-Key": _wai_key} if _wai_key else {}

            _ctx_vars = {
                k: v for k, v in ctx.items()
                if not k.startswith("_") and isinstance(v, (str, int, float, bool))
            }

            _payload = {
                "model":         _actual_model,
                "system_prompt": sys_prompt,
                "messages":      history,
                "variables":     _ctx_vars,
                "temperature":   temperature,
                "max_tokens":    1024,
            }
            if _provider:
                _payload["provider"] = _provider

            try:
                async with httpx.AsyncClient(timeout=120.0) as _hc:
                    _r = await _hc.post(
                        f"{_wai_url}/api/inference",
                        headers=_wai_hdrs,
                        json=_payload,
                    )
                _data = _r.json()
                if _data.get("ok"):
                    ai_text = str(_data.get("response", ""))
                else:
                    ai_text = f"[AI error: {_data.get('error', 'unknown')}]"
            except Exception as _exc:
                ai_text = f"[WizzardAI unavailable: {_exc}]"
                _log.error("ai_bot: WizzardAI call failed: %s", _exc)

            history.append({"role": "assistant", "content": ai_text})
            turns += 1

            _user_exit = exit_kws and last_msg and any(kw in last_msg.lower() for kw in exit_kws)
            _turns_max = turns >= max_turns

            if out_var:
                # Single-shot mode: store response in variable and advance
                ctx[out_var] = ai_text
                ctx.pop("_aibot_history", None)
                ctx.pop("_aibot_turns", None)
                current_id = _next_node_id(edges, current_id)
            elif _user_exit or _turns_max:
                # Exit: send final response then follow exit / default edge
                await send({"type": "message", "from": "bot", "text": ai_text, "timestamp": _ts()})
                _log_msg(session, "bot", ai_text, subtype="ai_bot")
                ctx.pop("_aibot_history", None)
                ctx.pop("_aibot_turns", None)
                current_id = _next_node_id(edges, current_id, "exit" if _user_exit else "default")
            else:
                # Multi-turn: send response and wait for next visitor message
                ctx["_aibot_history"] = history
                ctx["_aibot_turns"]   = turns
                await send({"type": "message", "from": "bot", "text": ai_text, "timestamp": _ts()})
                _log_msg(session, "bot", ai_text, subtype="ai_bot")
                session.flow_context  = ctx
                session.waiting_node_id = current_id
                _log.info("ai_bot multi-turn: saved history len=%d turns=%d ctx_keys=%s",
                          len(history), turns, sorted(ctx.keys()))
                await db.flush()
                return

        # ── Translate ─────────────────────────────────────────────────────────────
        elif node.node_type == "translate":
            _lt_base    = (_settings.libretranslate_url or "http://localhost:5000").rstrip("/")
            _lt_api_key = _settings.libretranslate_api_key or ""
            # Per-node overrides take precedence over global settings
            _lt_url_cfg = config.get("libretranslate_url", "").strip()
            _lt_key_cfg = config.get("api_key", "").strip()
            if _lt_url_cfg:
                _lt_base = _lt_url_cfg.rstrip("/")
            if _lt_key_cfg:
                _lt_api_key = _lt_key_cfg

            _mode        = config.get("mode", "translate")          # translate | detect_only
            _input_var   = config.get("input_variable", "message")
            _target_lang = _resolve_template(config.get("target_language", "en"), ctx)
            _source_lang = _resolve_template(config.get("source_language", "auto"), ctx) or "auto"
            _result_var  = config.get("result_variable", "translated_text")
            _lang_var    = config.get("language_variable", "contact.language")

            _input_text  = str(_resolve_path(ctx, _input_var) or "").strip()

            if not _input_text:
                # Nothing to translate — skip silently on the success path
                current_id = _next_node_id(edges, current_id, "success")
            else:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as _hc:
                        if _mode == "detect_only" or _source_lang == "auto":
                            # Detect language first
                            _det_payload: dict = {"q": _input_text}
                            if _lt_api_key:
                                _det_payload["api_key"] = _lt_api_key
                            _det_r = await _hc.post(
                                f"{_lt_base}/detect",
                                json=_det_payload,
                                headers={"Content-Type": "application/json"},
                            )
                            _det_data = _det_r.json()
                            if isinstance(_det_data, list) and _det_data:
                                _detected = _det_data[0].get("language", "en")
                            else:
                                _detected = "en"
                            _source_lang = _detected
                            if _lang_var:
                                _set_path(ctx, _lang_var, _detected)

                        if _mode == "detect_only":
                            # Language detection done — no translation requested
                            current_id = _next_node_id(edges, current_id, "success")
                        else:
                            _tr_payload: dict = {
                                "q":      _input_text,
                                "source": _source_lang,
                                "target": _target_lang,
                            }
                            if _lt_api_key:
                                _tr_payload["api_key"] = _lt_api_key
                            _tr_r = await _hc.post(
                                f"{_lt_base}/translate",
                                json=_tr_payload,
                                headers={"Content-Type": "application/json"},
                            )
                            _tr_data = _tr_r.json()
                            if "error" in _tr_data:
                                ctx["_translate_error"] = _tr_data["error"]
                                _log.warning("translate node: LibreTranslate error: %s", _tr_data["error"])
                                current_id = _next_node_id(edges, current_id, "error")
                            else:
                                _translated = _tr_data.get("translatedText", _input_text)
                                if _result_var:
                                    _set_path(ctx, _result_var, _translated)
                                if _lang_var and _source_lang != "auto":
                                    _set_path(ctx, _lang_var, _source_lang)
                                current_id = _next_node_id(edges, current_id, "success")
                except Exception as _tr_exc:
                    ctx["_translate_error"] = str(_tr_exc)
                    _log.warning("translate node: request failed: %s", _tr_exc)
                    current_id = _next_node_id(edges, current_id, "error")

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
        ctx = dict(session.flow_context or {})
        # Use the active flow (sub-flow support) rather than the connector's root flow
        _flow_id_for_lookup = ctx.get("_current_flow_id") or (
            str(connector.flow_id) if connector and connector.flow_id else None
        )
        if _flow_id_for_lookup:
            nodes, edges = await _load_flow_graph(_flow_id_for_lookup, db)
        else:
            nodes, edges = {}, []
        _wn_id_str = str(session.waiting_node_id)        # UUID → str for dict lookup
        waiting_node = nodes.get(_wn_id_str)

        if waiting_node:
            config = waiting_node.config or {}
            if waiting_node.node_type in ("input", "dtmf"):
                variable = config.get("variable", "input")

                if waiting_node.node_type == "input":
                    import re as _re
                    _validation = (config.get("validation") or "").strip()
                    _error_msg  = config.get("error_message", "Invalid input. Please try again.")
                    _max_retry  = max(1, int(config.get("max_retries") or 3))
                    _named_patterns = {
                        "number": r"^\d+$",
                        "email":  r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                        "phone":  r"^\+?[\d\s\(\)\-]{7,20}$",
                        "date":   r"^\d{4}-\d{2}-\d{2}$",
                    }
                    _pattern = _named_patterns.get(_validation, _validation) if _validation not in ("", "any") else ""

                    if _pattern and not _re.match(_pattern, text.strip()):
                        # Input failed validation
                        _retry_key   = f"_retry_{_wn_id_str}"
                        _retry_count = ctx.get(_retry_key, 0) + 1
                        if _retry_count >= _max_retry:
                            # Max retries exhausted — route to timeout handle
                            ctx.pop(_retry_key, None)
                            ctx["_input_timeout"] = _wn_id_str
                            ctx[variable] = text  # store for audit even though invalid
                        else:
                            ctx[_retry_key] = _retry_count
                            session.flow_context = ctx
                            await db.commit()
                            _log_msg(session, "bot", _error_msg)
                            await manager.send_visitor(session.session_key, {
                                "type": "message", "from": "bot",
                                "text": _error_msg, "timestamp": _ts(),
                            })
                            return  # stay at same input node
                    else:
                        ctx.pop(f"_retry_{_wn_id_str}", None)  # clear on success
                        ctx[variable] = text
                else:
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

            elif waiting_node.node_type == "ai_bot":
                # Pass the visitor message to the ai_bot handler via context
                _log.info("handle_visitor_msg: ai_bot waiting node — setting _aibot_last_msg")
                ctx["_aibot_last_msg"] = text

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
            channel="chat",
            direction="inbound",
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)

    return connector, session, is_new


# ─────────────────────────────────────────────────────────────────────────────
# SSE stream  GET /sse/chat/{api_key}/{session_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sse/chat/{api_key}/{session_id}")
async def visitor_sse(api_key: str, session_id: str, request: Request):
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
                    channel="chat",
                    direction="inbound",
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
            allowed_origins = list(connector.allowed_origins or ["*"])
            session_key = session.session_key
            # Clear any stale disconnect time — visitor is (re-)connecting
            session.visitor_last_seen = None
            await db.commit()
    except Exception as e:
        _log.exception("SSE: DB error setting up session: %s", e)
        return JSONResponse({"detail": "Server error"}, status_code=500)

    # Enforce connector allowed_origins: reflect the request Origin if it is
    # in the allow-list, otherwise fall back to the first allowed origin.
    # Using "*" with credentialed requests is invalid in browsers.
    request_origin = request.headers.get("origin", "")
    if "*" in allowed_origins:
        acao = "*"
    elif request_origin and request_origin in allowed_origins:
        acao = request_origin
    elif allowed_origins:
        acao = allowed_origins[0]
    else:
        acao = "null"

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
            # Record the time the visitor went offline so the sweep task can
            # auto-close the interaction after the configured timeout.
            try:
                async with async_session() as disc_db:
                    sr = await disc_db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    si = sr.scalar_one_or_none()
                    if si and si.status != "closed":
                        si.visitor_last_seen = datetime.utcnow()
                        await disc_db.commit()
            except Exception as _de:
                _log.warning("visitor_last_seen update failed for %s: %s", session_key, _de)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": acao,
            # Allow credentials only when a specific origin is reflected (not *)
            **({
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            } if acao != "*" else {}),
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
                _err_node = (session.flow_context or {}).get('_exec_node_id')
                _err_flow = (session.flow_context or {}).get('_exec_flow_id')
                if _err_node and _err_flow:
                    await _record_event_by_node_id(_err_flow, _err_node, db, 'error')
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
            _err_node = (session.flow_context or {}).get('_exec_node_id')
            _err_flow = (session.flow_context or {}).get('_exec_flow_id')
            if _err_node and _err_flow:
                await _record_event_by_node_id(_err_flow, _err_node, db, 'error')

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
    """Visitor explicitly ends the session.

    If an agent is handling the session, entering WRAP_UP gives the agent time
    to add notes and select an outcome before going available again.  A
    background task auto-closes the session after WRAP_UP_TIMEOUT_SECS if the
    agent does not act.
    """
    async with async_session() as db:
        _, session, _ = await _load_connector_and_session(
            api_key, session_id, db, create_if_missing=False
        )
        if session:
            if session.agent_id and session.status == "with_agent":
                # ── Enter wrap-up: agent keeps the session, clock starts ──────
                # Segment: close the agent segment (conversation over), summarise immediately
                _close_segment(session, "agent")
                session.status = "wrap_up"
                session.wrap_started_at = datetime.utcnow()
                await db.commit()
                await manager.send_agent(str(session.agent_id), {
                    "type": "session_visitor_left",
                    "session_id": session_id,
                    "wrap_seconds": WRAP_UP_TIMEOUT_SECS,
                })
                # Fire segment summary while wrap-up is active (pre-fill notes panel)
                asyncio.create_task(_summarise_segment_async(session_id))
                # Background auto-close if agent ignores the timer
                asyncio.create_task(
                    _auto_close_wrap(session_id, str(session.agent_id), WRAP_UP_TIMEOUT_SECS)
                )
            else:
                # No agent or already in a different state — close immediately
                if session.agent_id:
                    await manager.send_agent(str(session.agent_id), {
                        "type": "session_closed",
                        "session_id": session_id,
                    })
                if session.waiting_node_id:
                    _fctx = session.flow_context or {}
                    _flow_id = _fctx.get("_current_flow_id") or _fctx.get("_exec_flow_id")
                    if _flow_id:
                        try:
                            await _record_event_by_node_id(
                                _flow_id,
                                str(session.waiting_node_id),
                                db,
                                event_type="abandon",
                            )
                        except Exception as _ae:
                            _log.warning("visitor_close: failed to log abandon: %s", _ae)
                    session.waiting_node_id = None
                session.status = "closed"
                await db.commit()
                asyncio.create_task(_fire_chat_ended_event(
                    session_key=session_id,
                    connector_id=str(session.connector_id) if session.connector_id else None,
                    closed_by="visitor",
                    channel=(session.visitor_metadata or {}).get("channel", "chat"),
                    contact_id=str(session.contact_id) if getattr(session, "contact_id", None) else None,
                    queue_id=str(session.queue_id) if session.queue_id else None,
                ))
                asyncio.create_task(_dispatch_conversation_event(session_id, "conversation.closed", "visitor"))
        manager.disconnect_visitor(session_id)
    return {"ok": True}


async def _auto_close_wrap(session_key: str, agent_id: str, timeout: int) -> None:
    """Background task: auto-close a wrap_up session if the agent does not submit
    an outcome within *timeout* seconds."""
    await asyncio.sleep(timeout + 5)  # small grace period on top of the UI countdown
    from app.database import async_session as _as
    async with _as() as db:
        res = await db.execute(
            select(Interaction).where(Interaction.session_key == session_key)
        )
        sess = res.scalar_one_or_none()
        if sess and sess.status == "wrap_up":
            if sess.wrap_started_at:
                delta = datetime.utcnow() - sess.wrap_started_at
                sess.wrap_time = max(0, int(delta.total_seconds()))
            sess.status = "closed"
            sess.disconnect_outcome = "resolve"
            await db.commit()
            _log.info("wrap-up auto-closed: session=%s agent=%s", session_key, agent_id)
            await manager.send_agent(agent_id, {
                "type": "session_closed",
                "session_id": session_key,
            })


# ─────────────────────────────────────────────────────────────────────────────
# Session outcomes  GET /api/v1/sessions/{session_key}/outcomes
# ─────────────────────────────────────────────────────────────────────────────

_RESOLVE_FALLBACK = {
    "id": None,
    "code": "resolve",
    "label": "Resolve",
    "outcome_type": "positive",
    "action_type": "end_interaction",
    "redirect_flow_id": None,
    "description": "Mark as resolved and close the interaction.",
    "is_active": True,
}


@router.get("/api/v1/sessions/{session_key}/outcomes",
            dependencies=[Depends(get_current_user)])
async def get_session_outcomes(session_key: str, db: AsyncSession = Depends(get_db)):
    """Return the agent-selectable outcomes for a session's queue.

    Always includes a built-in 'Resolve' fallback when no outcomes are configured.
    The caller passes the returned ``id`` back via the ``close_with_outcome``
    WebSocket message.
    """
    res = await db.execute(
        select(Interaction).where(Interaction.session_key == session_key)
    )
    sess = res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    outcome_ids: list = []
    if sess.queue_id:
        q_res = await db.execute(select(Queue).where(Queue.id == sess.queue_id))
        queue = q_res.scalar_one_or_none()
        if queue:
            outcome_ids = [str(oid) for oid in (queue.outcomes or [])]

    results = []

    if outcome_ids:
        # Queue has explicit outcome assignments — load only those
        parsed_ids = []
        for raw in outcome_ids:
            try:
                parsed_ids.append(_uuid_mod.UUID(str(raw)))
            except (ValueError, AttributeError):
                pass
        if parsed_ids:
            o_res = await db.execute(
                select(Outcome)
                .where(Outcome.id.in_(parsed_ids), Outcome.is_active == True)  # noqa: E712
                .order_by(Outcome.label)
            )
            for o in o_res.scalars().all():
                results.append({
                    "id": str(o.id),
                    "code": o.code,
                    "label": o.label,
                    "outcome_type": o.outcome_type,
                    "action_type": o.action_type,
                    "redirect_flow_id": str(o.redirect_flow_id) if o.redirect_flow_id else None,
                    "description": o.description,
                    "is_active": o.is_active,
                })

    if not results:
        # No queue-specific outcomes — return every active outcome in the system
        all_res = await db.execute(
            select(Outcome)
            .where(Outcome.is_active == True)  # noqa: E712
            .order_by(Outcome.label)
        )
        for o in all_res.scalars().all():
            results.append({
                "id": str(o.id),
                "code": o.code,
                "label": o.label,
                "outcome_type": o.outcome_type,
                "action_type": o.action_type,
                "redirect_flow_id": str(o.redirect_flow_id) if o.redirect_flow_id else None,
                "description": o.description,
                "is_active": o.is_active,
            })

    # Always guarantee at least one selectable outcome.
    if not results:
        results.append(_RESOLVE_FALLBACK)

    return results


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

        # Mark agent online in DB so the dashboard stat is accurate
        try:
            agent_rec = await db.execute(select(User).where(User.id == _uuid_mod.UUID(user_id)))
            agent_obj = agent_rec.scalar_one_or_none()
            if agent_obj:
                agent_obj.is_online = True
                await db.commit()
        except Exception as _oe:
            _log.warning("Could not set is_online=True for agent %s: %s", user_id, _oe)

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
                        # ── Capacity check ────────────────────────────────────
                        agent_res_cap = await db.execute(select(User).where(User.id == _uuid_mod.UUID(user_id)))
                        agent_cap_obj = agent_res_cap.scalar_one_or_none()
                        if agent_cap_obj:
                            caps = _get_effective_caps(agent_cap_obj)
                            sess_channel = (sess.channel or "chat").lower()
                            if _at_cap(caps, user_id, manager, sess_channel, bool(agent_cap_obj.capacity_override_active)):
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "message": "capacity_exceeded",
                                    "detail": "You are at your maximum concurrent interaction limit.",
                                }))
                                continue  # do not assign
                            # Consume pick-next override if it was armed
                            if agent_cap_obj.capacity_override_active:
                                agent_cap_obj.capacity_override_active = False
                                await db.flush()
                        sess.agent_id = _uuid_mod.UUID(user_id)
                        # Segment: close queue wait, open agent handling phase
                        _close_segment(sess, "queue")
                        _open_segment(sess, "agent", agent_id=user_id)
                        sess.status = "with_agent"
                        await db.flush()
                        # Get agent name
                        agent_res = await db.execute(select(User).where(User.id == sess.agent_id))
                        agent = agent_res.scalar_one_or_none()
                        agent_name = agent.full_name if agent else "Agent"
                        manager.agent_load[user_id] = manager.agent_load.get(user_id, 0) + 1
                        # Also track per-channel load
                        _sess_ch = (sess.channel or "chat").lower()
                        _ch_map = manager.agent_channel_load.setdefault(user_id, {})
                        _ch_map[_sess_ch] = _ch_map.get(_sess_ch, 0) + 1
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
                        await _push_capacity_update(user_id, manager)

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
                        _rel_ch = (sess.channel or "chat").lower()
                        manager.agent_load[user_id] = max(0, manager.agent_load.get(user_id, 1) - 1)
                        _ch_rel = manager.agent_channel_load.setdefault(user_id, {})
                        _ch_rel[_rel_ch] = max(0, _ch_rel.get(_rel_ch, 1) - 1)
                        sess.agent_id = None
                        sess.status = "waiting_agent"
                        await db.flush()
                        await manager.send_visitor(session_key, {
                            "type": "queue",
                            "message": "Agent has released the session. Waiting for next available agent.",
                            "timestamp": _ts(),
                        })
                        await db.commit()
                        await _push_capacity_update(user_id, manager)

                # ── Agent closes session ──────────────────────────────────────
                elif msg_type == "close":
                    session_key = msg.get("session_id", "")
                    res4 = await db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    sess = res4.scalar_one_or_none()
                    if sess:
                        _close_ch  = (sess.channel or "chat").lower()
                        _was_mine  = bool(sess.agent_id and str(sess.agent_id) == user_id)
                        if _was_mine:
                            manager.agent_load[user_id] = max(0, manager.agent_load.get(user_id, 1) - 1)
                            _ch_cls = manager.agent_channel_load.setdefault(user_id, {})
                            _ch_cls[_close_ch] = max(0, _ch_cls.get(_close_ch, 1) - 1)
                        sess.status = "closed"
                        await db.flush()
                        await manager.send_visitor(session_key, {
                            "type": "end",
                            "status": "closed_by_agent",
                            "message": "The agent has ended the session.",
                            "timestamp": _ts(),
                        })
                        await db.commit()
                        asyncio.create_task(_summarise_async(session_key))
                        asyncio.create_task(_notify_wizzardqa(session_key))
                        asyncio.create_task(_fire_chat_ended_event(
                            session_key=session_key,
                            connector_id=str(sess.connector_id) if sess.connector_id else None,
                            closed_by="agent",
                            channel=(sess.visitor_metadata or {}).get("channel", "chat"),
                            contact_id=str(sess.contact_id) if getattr(sess, "contact_id", None) else None,
                            queue_id=str(sess.queue_id) if sess.queue_id else None,
                        ))
                        asyncio.create_task(_dispatch_conversation_event(session_key, "conversation.closed", "agent"))
                        await websocket.send_text(json.dumps({
                            "type": "session_closed",
                            "session_id": session_key,
                        }))
                        if _was_mine:
                            await _push_capacity_update(user_id, manager)

                # ── Agent closes session with a selected outcome ───────────────
                elif msg_type == "close_with_outcome":
                    session_key = msg.get("session_id", "")
                    outcome_id  = msg.get("outcome_id")  # UUID string or None
                    wrap_notes  = msg.get("notes")       # optional agent notes from wrap-up panel

                    res_cwo = await db.execute(
                        select(Interaction).where(Interaction.session_key == session_key)
                    )
                    sess = res_cwo.scalar_one_or_none()
                    if not sess:
                        continue

                    # Persist any notes the agent added during wrap-up
                    if wrap_notes and isinstance(wrap_notes, str):
                        sess.notes = wrap_notes.strip() or sess.notes

                    # Resolve the outcome record (None ⇒ built-in Resolve fallback)
                    outcome: Optional[Outcome] = None
                    if outcome_id:
                        try:
                            o_res = await db.execute(
                                select(Outcome).where(Outcome.id == _uuid_mod.UUID(str(outcome_id)))
                            )
                            outcome = o_res.scalar_one_or_none()
                        except (ValueError, AttributeError):
                            outcome = None

                    _cwo_ch   = (sess.channel or "chat").lower()
                    _cwo_mine = bool(sess.agent_id and str(sess.agent_id) == user_id)
                    action, outcome_code = apply_outcome_to_session(
                        sess, outcome, manager.agent_load, user_id
                    )
                    # Mirror channel load decrement (apply_outcome_to_session only adjusts agent_load)
                    if _cwo_mine:
                        _ch_cwo = manager.agent_channel_load.setdefault(user_id, {})
                        _ch_cwo[_cwo_ch] = max(0, _ch_cwo.get(_cwo_ch, 1) - 1)
                    await db.flush()

                    if action == "end":
                        await manager.send_visitor(session_key, {
                            "type": "end",
                            "status": "closed_by_agent",
                            "message": "The agent has ended the session.",
                            "timestamp": _ts(),
                        })
                        await db.commit()
                        asyncio.create_task(_summarise_async(session_key))
                        asyncio.create_task(_notify_wizzardqa(session_key))
                        await websocket.send_text(json.dumps({
                            "type": "session_closed",
                            "session_id": session_key,
                        }))
                        if _cwo_mine:
                            await _push_capacity_update(user_id, manager)

                    else:  # redirect
                        conn_res = await db.execute(
                            select(Connector).where(Connector.id == sess.connector_id)
                        )
                        connector = conn_res.scalar_one_or_none()
                        # Notify the agent panel immediately so the session card
                        # moves to "In Flow" before the flow starts executing
                        # (which may include long wait nodes).
                        await websocket.send_text(json.dumps({
                            "type": "session_flow_redirected",
                            "session_id": session_key,
                            "outcome_code": outcome_code,
                        }))
                        # Run the redirect flow. connector may be None — run_flow
                        # uses _current_flow_id from session.flow_context directly.
                        _log.info(
                            "close_with_outcome redirect: session=%s flow_context=%s connector=%s",
                            session_key, sess.flow_context, connector,
                        )
                        await run_flow(sess, connector, db, agent_ws=websocket)
                        await db.commit()
                        if _cwo_mine:
                            await _push_capacity_update(user_id, manager)
                        # If the flow ran to completion and closed the session,
                        # remove it from the panel.
                        if sess.status == "closed":
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
                    # up to the agent's omni + per-channel capacity limits.
                    if new_status == "available":
                        # Use a fresh DB session for the sweep so the long-lived agent WS
                        # session's stale transaction doesn't hide recently-committed sessions.
                        async with async_session() as sweep_db:
                            try:
                                agent_res = await sweep_db.execute(select(User).where(User.id == _uuid_mod.UUID(user_id)))
                                agent_obj = agent_res.scalar_one_or_none()

                                # Build effective capacity from agent overrides + global defaults
                                caps = _get_effective_caps(agent_obj) if agent_obj else {"omni": 5, "voice": 1, "chat": 5, "whatsapp": 3, "email": 5, "sms": 5}
                                omni_limit   = caps["omni"]
                                current_load = manager.agent_load.get(user_id, 0)
                                slots = omni_limit - current_load
                                _log.info(
                                    "Availability sweep for %s: omni_max=%s load=%s slots=%s",
                                    user_id, omni_limit, current_load, slots,
                                )

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

                                        # Per-channel cap check
                                        sess_channel = (w_sess.channel or "chat").lower()
                                        chan_limit = caps.get(sess_channel, caps["omni"])
                                        chan_load  = _channel_load(user_id, manager, sess_channel)
                                        if chan_load >= chan_limit:
                                            _log.info(
                                                "Sweep skip %s: channel '%s' at cap %s/%s",
                                                sess_key, sess_channel, chan_load, chan_limit,
                                            )
                                            continue

                                        w_sess.agent_id = _uuid_mod.UUID(user_id)
                                        w_sess.status = "with_agent"
                                        await sweep_db.flush()  # write but don't commit yet
                                        # Update in-memory load counters
                                        manager.agent_load[user_id] = manager.agent_load.get(user_id, 0) + 1
                                        ch_map = manager.agent_channel_load.setdefault(user_id, {})
                                        ch_map[sess_channel] = ch_map.get(sess_channel, 0) + 1
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

                # ── Agent voice call controls ──────────────────────────────
                elif msg_type in ("call_hold", "call_unhold", "call_mute", "call_unmute", "call_hangup", "call_transfer_number"):
                    _vc_attempt_str = msg.get("attempt_id", "")
                    if not _vc_attempt_str:
                        continue
                    try:
                        _vc_uuid = _uuid_mod.UUID(_vc_attempt_str)
                    except ValueError:
                        continue

                    _vc_att_res = await db.execute(
                        select(CampaignAttempt).where(CampaignAttempt.id == _vc_uuid)
                    )
                    _vc_att = _vc_att_res.scalar_one_or_none()
                    # Only the assigned agent may control this call
                    if not _vc_att or str(_vc_att.agent_id) != user_id:
                        continue

                    # Resolve voice connector
                    _vc_camp_res = await db.execute(
                        select(Campaign).where(Campaign.id == _vc_att.campaign_id)
                    )
                    _vc_camp = _vc_camp_res.scalar_one_or_none()
                    _vc_id_str = ((_vc_camp.settings or {}).get("voice_connector_id")) if _vc_camp else None
                    _vc_conn: VoiceConnector | None = None
                    if _vc_id_str:
                        try:
                            _vc_cr = await db.execute(
                                select(VoiceConnector).where(
                                    VoiceConnector.id == _uuid_mod.UUID(str(_vc_id_str))
                                )
                            )
                            _vc_conn = _vc_cr.scalar_one_or_none()
                        except (ValueError, Exception):
                            pass

                    # Parse contact CallSid from notes ("twilio_ref:CAxxxx" or "twilio_ref:CAxxxx;...")
                    _vc_notes = _vc_att.notes or ""
                    _vc_call_sid = ""
                    for _part in _vc_notes.split(";"):
                        if _part.strip().startswith("twilio_ref:"):
                            _vc_call_sid = _part.strip()[len("twilio_ref:"):]
                            break
                    _vc_conf_name = f"outbound-{_vc_att.id}"

                    _is_twilio = (
                        _vc_conn
                        and _vc_conn.provider == "twilio"
                        and _vc_conn.account_sid
                        and _vc_conn.auth_token
                    )

                    if _is_twilio:
                        _acct = _vc_conn.account_sid
                        _tok  = _vc_conn.auth_token
                        if msg_type == "call_hangup":
                            if _vc_call_sid:
                                await _twilio_call_action(_acct, _tok, _vc_call_sid)
                            await manager.send_agent(user_id, {
                                "type": "call_ended", "attempt_id": _vc_attempt_str, "reason": "hangup",
                            })
                        elif msg_type == "call_hold":
                            if _vc_call_sid:
                                await _twilio_conference_participant(
                                    _acct, _tok, _vc_conf_name, _vc_call_sid, Hold="true"
                                )
                            await manager.send_agent(user_id, {
                                "type": "call_hold_ack", "attempt_id": _vc_attempt_str, "held": True,
                            })
                        elif msg_type == "call_unhold":
                            if _vc_call_sid:
                                await _twilio_conference_participant(
                                    _acct, _tok, _vc_conf_name, _vc_call_sid, Hold="false"
                                )
                            await manager.send_agent(user_id, {
                                "type": "call_hold_ack", "attempt_id": _vc_attempt_str, "held": False,
                            })
                        elif msg_type == "call_mute":
                            await _twilio_mute_agent_participant(
                                _acct, _tok, _vc_conf_name, _vc_call_sid, muted=True
                            )
                            await manager.send_agent(user_id, {
                                "type": "call_mute_ack", "attempt_id": _vc_attempt_str, "muted": True,
                            })
                        elif msg_type == "call_unmute":
                            await _twilio_mute_agent_participant(
                                _acct, _tok, _vc_conf_name, _vc_call_sid, muted=False
                            )
                            await manager.send_agent(user_id, {
                                "type": "call_mute_ack", "attempt_id": _vc_attempt_str, "muted": False,
                            })
                        elif msg_type == "call_transfer_number":
                            to_number = (msg.get("to_number") or "").strip()
                            if not to_number:
                                await manager.send_agent(user_id, {
                                    "type": "call_transfer_ack",
                                    "attempt_id": _vc_attempt_str,
                                    "ok": False,
                                    "error": "no to_number supplied",
                                })
                            else:
                                from_number = (
                                    getattr(_vc_conn, "caller_id_override", None)
                                    or ((_vc_conn.did_numbers or [None])[0] if _vc_conn.did_numbers else None)
                                    or ""
                                )
                                base_url = _settings.public_base_url.rstrip("/")
                                twiml_url = f"{base_url}/api/v1/voice/twiml/transfer/{_vc_attempt_str}"
                                transfer_sid = await _twilio_warm_transfer(
                                    _acct, _tok,
                                    from_number=from_number,
                                    to_number=to_number,
                                    twiml_url=twiml_url,
                                )
                                await manager.send_agent(user_id, {
                                    "type": "call_transfer_ack",
                                    "attempt_id": _vc_attempt_str,
                                    "ok": bool(transfer_sid),
                                    "transfer_call_sid": transfer_sid or "",
                                    "to_number": to_number,
                                    "error": "" if transfer_sid else "Twilio call failed — check credentials and numbers",
                                })
                    else:
                        # No Twilio connector configured — send optimistic ack so the UI updates
                        if msg_type == "call_hangup":
                            await manager.send_agent(user_id, {
                                "type": "call_ended", "attempt_id": _vc_attempt_str, "reason": "hangup",
                            })
                        elif msg_type in ("call_hold", "call_unhold"):
                            await manager.send_agent(user_id, {
                                "type": "call_hold_ack",
                                "attempt_id": _vc_attempt_str,
                                "held": msg_type == "call_hold",
                            })
                        elif msg_type in ("call_mute", "call_unmute"):
                            await manager.send_agent(user_id, {
                                "type": "call_mute_ack",
                                "attempt_id": _vc_attempt_str,
                                "muted": msg_type == "call_mute",
                            })

        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect_agent(user_id)
            # Mark agent offline in DB
            try:
                async with async_session() as cleanup_db:
                    off_rec = await cleanup_db.execute(select(User).where(User.id == _uuid_mod.UUID(user_id)))
                    off_obj = off_rec.scalar_one_or_none()
                    if off_obj:
                        off_obj.is_online = False
                        await cleanup_db.commit()
            except Exception as _of:
                _log.warning("Could not set is_online=False for agent %s: %s", user_id, _of)
