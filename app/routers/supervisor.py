"""Supervisor control plane — live monitoring, barge-in, coaching, and reassignment.

Endpoints
---------
GET  /api/v1/supervisor/live-calls
    All CampaignAttempts currently in CONNECTED status (active voice calls).

GET  /api/v1/supervisor/live-sessions
    All Conversations in ACTIVE or WAITING status (live chat, voice-chat sessions).

GET  /api/v1/supervisor/agents-online
    All agents currently connected via WebSocket with their availability and load.

POST /api/v1/supervisor/barge/{attempt_id}
    Join a live Twilio conference as listener, barge (full), or whisper (coach).
    - If `supervisor_phone` is supplied → system dials the supervisor's phone.
    - Otherwise              → returns a Twilio browser-SDK token and connect params.

POST /api/v1/supervisor/chat-message/{conversation_id}
    Inject a supervisor coaching note visible only to the assigned agent.

POST /api/v1/supervisor/reassign/chat/{conversation_id}
    Reassign (or claim) a chat / omnichannel conversation.

POST /api/v1/supervisor/reassign/voice/{attempt_id}
    Reassign a live voice attempt to a different agent.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    AttemptStatus,
    CampaignAttempt,
    Campaign,
    Contact,
    Conversation,
    ConversationStatus,
    User,
    VoiceConnector,
)
from app.routers.chat_ws import manager

router = APIRouter(
    prefix="/api/v1/supervisor",
    tags=["supervisor"],
    dependencies=[Depends(get_current_user)],
)

_log = logging.getLogger("supervisor")
_settings = get_settings()
_TWILIO_SDK_URL = "https://sdk.twilio.com/js/voice/2.10/twilio.min.js"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _contact_display(c: Contact | None) -> str:
    if not c:
        return "—"
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    return name or c.phone or "—"


# ── Live voice calls ──────────────────────────────────────────────────────────

@router.get("/live-calls", summary="List active voice calls")
async def live_calls(db: AsyncSession = Depends(get_db)):
    """Return all CampaignAttempt rows currently in CONNECTED status.

    Each row includes the conference name, connector ID, and elapsed seconds so
    the supervisor page can display live duration and provide barge-in controls.
    """
    result = await db.execute(
        select(CampaignAttempt)
        .where(CampaignAttempt.status == AttemptStatus.CONNECTED)
        .order_by(CampaignAttempt.connected_at)
    )
    attempts = result.scalars().all()

    # Deduplicate DB round-trips by collecting IDs and batch-loading
    campaign_ids = {att.campaign_id for att in attempts if att.campaign_id}
    agent_ids    = {att.agent_id    for att in attempts if att.agent_id}
    contact_ids  = {att.contact_id  for att in attempts if att.contact_id}

    camps = {}
    if campaign_ids:
        rows = (await db.execute(select(Campaign).where(Campaign.id.in_(campaign_ids)))).scalars().all()
        camps = {c.id: c for c in rows}

    agents = {}
    if agent_ids:
        rows = (await db.execute(select(User).where(User.id.in_(agent_ids)))).scalars().all()
        agents = {u.id: u for u in rows}

    contacts = {}
    if contact_ids:
        rows = (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars().all()
        contacts = {c.id: c for c in rows}

    # Collect connector IDs from campaign settings for a single batch query
    connector_map: dict[uuid.UUID, str | None] = {}
    connector_ids: set[uuid.UUID] = set()
    for att in attempts:
        camp = camps.get(att.campaign_id)
        cid_str = None
        if camp:
            cid_str = (camp.outbound_config or {}).get("voice_connector_id") or \
                      (camp.settings or {}).get("voice_connector_id")
        connector_map[att.id] = cid_str
        if cid_str:
            try:
                connector_ids.add(uuid.UUID(str(cid_str)))
            except ValueError:
                pass

    now = _utcnow()
    rows = []
    for att in attempts:
        camp     = camps.get(att.campaign_id)
        agent    = agents.get(att.agent_id) if att.agent_id else None
        contact  = contacts.get(att.contact_id) if att.contact_id else None
        duration = int((now - att.connected_at).total_seconds()) if att.connected_at else None

        rows.append({
            "attempt_id":      str(att.id),
            "campaign_id":     str(att.campaign_id),
            "campaign_name":   camp.name if camp else None,
            "agent_id":        str(att.agent_id) if att.agent_id else None,
            "agent_name":      agent.full_name if agent else None,
            "contact_display": _contact_display(contact),
            "contact_phone":   contact.phone if contact else None,
            "connected_at":    att.connected_at.isoformat() if att.connected_at else None,
            "duration_seconds": duration,
            "conf_name":       f"outbound-{att.id}",
            "connector_id":    connector_map.get(att.id),
        })

    return rows


# ── Live chat / omnichannel sessions ─────────────────────────────────────────

@router.get("/live-sessions", summary="List active chat and voice-chat sessions")
async def live_sessions(db: AsyncSession = Depends(get_db)):
    """Return active and waiting Conversations for supervisor monitoring.

    Covers all channels (chat, voice, WhatsApp, SMS, email).
    """
    result = await db.execute(
        select(Conversation)
        .where(Conversation.status.in_([ConversationStatus.ACTIVE, ConversationStatus.WAITING]))
        .order_by(Conversation.started_at)
    )
    convs = result.scalars().all()

    agent_ids   = {c.agent_id   for c in convs if c.agent_id}
    contact_ids = {c.contact_id for c in convs if c.contact_id}

    agents = {}
    if agent_ids:
        rows = (await db.execute(select(User).where(User.id.in_(agent_ids)))).scalars().all()
        agents = {u.id: u for u in rows}

    contacts = {}
    if contact_ids:
        rows = (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars().all()
        contacts = {c.id: c for c in rows}

    now = _utcnow()
    out = []
    for conv in convs:
        agent   = agents.get(conv.agent_id) if conv.agent_id else None
        contact = contacts.get(conv.contact_id) if conv.contact_id else None
        elapsed = int((now - conv.started_at).total_seconds()) if conv.started_at else None

        out.append({
            "conversation_id": str(conv.id),
            "channel":         conv.channel.value if conv.channel else "chat",
            "status":          conv.status.value  if conv.status  else None,
            "agent_id":        str(conv.agent_id)   if conv.agent_id   else None,
            "agent_name":      agent.full_name       if agent           else None,
            "contact_display": _contact_display(contact),
            "queue_id":        str(conv.queue_id) if conv.queue_id else None,
            "started_at":      conv.started_at.isoformat() if conv.started_at else None,
            "elapsed_seconds": elapsed,
            "external_id":     conv.external_id,
        })

    return out


# ── Agents online ─────────────────────────────────────────────────────────────

@router.get("/agents-online", summary="Agents connected via WebSocket")
async def agents_online(db: AsyncSession = Depends(get_db)):
    """Return all agents currently connected to the agent WebSocket with live stats."""
    online_ids = list(manager.agents.keys())
    if not online_ids:
        return []

    uuid_ids = []
    for uid in online_ids:
        try:
            uuid_ids.append(uuid.UUID(uid))
        except ValueError:
            pass

    users = {}
    if uuid_ids:
        rows = (await db.execute(select(User).where(User.id.in_(uuid_ids)))).scalars().all()
        users = {str(u.id): u for u in rows}

    return [
        {
            "user_id":      uid,
            "full_name":    users[uid].full_name if uid in users else uid,
            "availability": manager.agent_availability.get(uid, "offline"),
            "load":         manager.agent_load.get(uid, 0),
            "campaign_id":  manager.agent_campaigns.get(uid),
        }
        for uid in online_ids
    ]


# ── Voice barge-in ────────────────────────────────────────────────────────────

class BargeRequest(BaseModel):
    connector_id:    uuid.UUID
    mode:            str = "listen"   # listen | barge | whisper
    supervisor_phone: str = ""        # E.164 — if set, system dials supervisor's phone
    coach_call_sid:  str = ""         # agent call SID (only needed for whisper mode)


@router.post("/barge/{attempt_id}", summary="Join a live voice call")
async def barge_in(
    attempt_id: uuid.UUID,
    body: BargeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dial the supervisor into the live conference for the given attempt.

    **listen**  — supervisor hears all participants but cannot be heard.
    **barge**   — supervisor joins as a full participant (3-way conversation).
    **whisper** — supervisor hears all and speaks *only* to the agent
                  (Twilio coaching feature; requires `coach_call_sid`).

    If `supervisor_phone` is provided, the platform places an outbound call to
    that number.  When the supervisor answers, TwiML joins their leg to the
    conference in the requested mode.

    Without `supervisor_phone`, the endpoint returns a Twilio browser-SDK token
    so the supervisor page can connect via ``Twilio.Device.connect()``.
    """
    # Validate the attempt is still live
    att_res = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    att = att_res.scalar_one_or_none()
    if not att or att.status != AttemptStatus.CONNECTED:
        raise HTTPException(status_code=404, detail="Live call not found or no longer active")

    # Load and validate the connector
    vc_res = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == body.connector_id)
    )
    vc = vc_res.scalar_one_or_none()
    if not vc or vc.provider != "twilio":
        raise HTTPException(status_code=400, detail="Connector not found or not a Twilio connector")

    base_url = _settings.public_base_url.rstrip("/")
    mode     = body.mode.lower()

    # ── Phone dial-in ─────────────────────────────────────────────────────────
    if body.supervisor_phone:
        params = f"mode={mode}"
        if mode == "whisper" and body.coach_call_sid:
            params += f"&coach_call_sid={body.coach_call_sid}"
        twiml_url = f"{base_url}/api/v1/voice/twiml/supervisor/{attempt_id}?{params}"
        from_number = (
            getattr(vc, "caller_id_override", None)
            or (vc.did_numbers[0] if vc.did_numbers else "")
        )
        creds = base64.b64encode(f"{vc.account_sid}:{vc.auth_token}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{vc.account_sid}/Calls.json",
                    data={"To": body.supervisor_phone, "From": from_number, "Url": twiml_url},
                    headers={"Authorization": f"Basic {creds}"},
                )
            if r.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail=f"Twilio error: {r.text[:200]}")
            return {"mode": mode, "call_sid": r.json().get("sid"), "method": "phone"}
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    # ── Browser SDK token ─────────────────────────────────────────────────────
    missing = [f for f in ("account_sid", "api_key", "api_secret", "twiml_app_sid")
               if not getattr(vc, f, None)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Connector missing WebRTC fields for Twilio browser SDK: {', '.join(missing)}",
        )
    try:
        from twilio.jwt.access_token import AccessToken
        from twilio.jwt.access_token.grants import VoiceGrant
        identity = f"supervisor-{current_user.id}"
        token = AccessToken(
            vc.account_sid, vc.api_key, vc.api_secret,
            identity=identity, ttl=3600,
        )
        token.add_grant(VoiceGrant(
            outgoing_application_sid=vc.twiml_app_sid,
            incoming_allow=False,
        ))
        return {
            "mode":            mode,
            "method":          "browser",
            "provider":        "twilio",
            "sdk_url":         _TWILIO_SDK_URL,
            "credentials":     {"token": token.to_jwt()},
            "identity":        identity,
            "attempt_id":      str(attempt_id),
            "conf_name":       f"outbound-{attempt_id}",
            "coach_call_sid":  body.coach_call_sid,
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="twilio package not installed")


# ── Supervisor coaching note (chat) ──────────────────────────────────────────

class CoachNoteRequest(BaseModel):
    message: str


@router.post("/chat-message/{conversation_id}", summary="Send a supervisor coaching note to the agent")
async def send_coach_note(
    conversation_id: uuid.UUID,
    body: CoachNoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push a supervisor-only coaching note to the agent handling this conversation.

    The note appears in the agent panel as a system message tagged
    ``supervisor_note`` and is not visible to the contact.
    """
    conv_res = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_res.scalar_one_or_none()
    if not conv or not conv.agent_id:
        raise HTTPException(status_code=404, detail="Conversation not found or no agent assigned")

    await manager.send_agent(str(conv.agent_id), {
        "type":            "supervisor_note",
        "conversation_id": str(conversation_id),
        "from_name":       current_user.full_name,
        "message":         body.message,
    })
    return {"ok": True}


# ── Chat / omnichannel reassignment ──────────────────────────────────────────

class ChatReassignRequest(BaseModel):
    to_agent_id: Optional[str] = None  # assign to specific agent
    to_queue_id: Optional[str] = None  # OR re-queue (clears agent_id)
    # If both are omitted the supervisor claims the conversation for themselves.


@router.post("/reassign/chat/{conversation_id}", summary="Reassign a chat conversation")
async def reassign_chat(
    conversation_id: uuid.UUID,
    body: ChatReassignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Take a conversation away from its current agent and reassign it.

    - Supply `to_agent_id` to assign directly to another agent.
    - Supply `to_queue_id` to re-queue (clears the agent assignment).
    - Omit both to claim the conversation for yourself (the supervisor).

    Both the old and new agents are notified via their WebSocket connections.
    """
    conv_res = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    old_agent_id = str(conv.agent_id) if conv.agent_id else None

    if body.to_queue_id:
        # Re-queue: clear agent, set new queue, back to waiting
        conv.agent_id = None
        conv.queue_id = uuid.UUID(body.to_queue_id)
        conv.status   = ConversationStatus.WAITING
        new_agent_id  = None
    else:
        new_agent_id = body.to_agent_id or str(current_user.id)
        conv.agent_id     = uuid.UUID(new_agent_id)
        conv.status       = ConversationStatus.ACTIVE
        conv.answered_at  = conv.answered_at or _utcnow()

    await db.commit()

    supervisor_label = current_user.full_name or str(current_user.id)

    # Notify old agent that the conversation was taken away
    if old_agent_id and old_agent_id != new_agent_id:
        await manager.send_agent(old_agent_id, {
            "type":            "session_reassigned",
            "session_id":      str(conversation_id),
            "by_supervisor":   str(current_user.id),
            "supervisor_name": supervisor_label,
        })

    # Notify new agent of the assignment
    if new_agent_id:
        new_agent_obj = None
        if new_agent_id:
            res = await db.execute(select(User).where(User.id == uuid.UUID(new_agent_id)))
            new_agent_obj = res.scalar_one_or_none()
        await manager.send_agent(new_agent_id, {
            "type":            "session_assigned",
            "session_id":      str(conversation_id),
            "channel":         conv.channel.value if conv.channel else "chat",
            "by_supervisor":   str(current_user.id),
            "supervisor_name": supervisor_label,
            "agent_name":      new_agent_obj.full_name if new_agent_obj else "",
        })

    return {"ok": True, "conversation_id": str(conversation_id)}


# ── Voice call reassignment ───────────────────────────────────────────────────

class VoiceReassignRequest(BaseModel):
    to_agent_id: str   # UUID string of the target agent


@router.post("/reassign/voice/{attempt_id}", summary="Reassign a live voice call")
async def reassign_voice(
    attempt_id: uuid.UUID,
    body: VoiceReassignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reassign a live CampaignAttempt to a different agent.

    Updates ``CampaignAttempt.agent_id`` and notifies both the displaced agent
    and the new agent via their WebSocket connections.  The voice conference
    itself is unaffected — the new agent must use their WebRTC device to join
    the conference for ``attempt_id``.
    """
    att_res = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    att = att_res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attempt not found")

    old_agent_id = str(att.agent_id) if att.agent_id else None
    att.agent_id = uuid.UUID(body.to_agent_id)
    await db.commit()

    supervisor_label = current_user.full_name or str(current_user.id)

    # Notify displaced agent
    if old_agent_id:
        await manager.send_agent(old_agent_id, {
            "type":            "call_reassigned",
            "attempt_id":      str(attempt_id),
            "by_supervisor":   str(current_user.id),
            "supervisor_name": supervisor_label,
        })

    # Notify new agent
    new_agent_res = await db.execute(
        select(User).where(User.id == uuid.UUID(body.to_agent_id))
    )
    new_agent = new_agent_res.scalar_one_or_none()
    camp_res = await db.execute(
        select(Campaign).where(Campaign.id == att.campaign_id)
    )
    camp = camp_res.scalar_one_or_none()

    # Derive connector_id for the new agent to know which device to use
    connector_id = None
    if camp:
        connector_id = (camp.outbound_config or {}).get("voice_connector_id") or \
                       (camp.settings or {}).get("voice_connector_id")

    await manager.send_agent(body.to_agent_id, {
        "type":            "call_assigned",
        "attempt_id":      str(attempt_id),
        "conf_name":       f"outbound-{attempt_id}",
        "connector_id":    connector_id,
        "campaign_name":   camp.name if camp else "",
        "by_supervisor":   str(current_user.id),
        "supervisor_name": supervisor_label,
        "agent_name":      new_agent.full_name if new_agent else "",
    })

    return {"ok": True, "attempt_id": str(attempt_id)}
