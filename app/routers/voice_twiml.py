"""TwiML / NCCO endpoints for outbound voice calls.

These endpoints are called by the telephony provider (Twilio, Telnyx, Vonage,
Africa's Talking), not by the WizzardChat UI.  They are not authenticated — the
URLs contain the attempt UUID which acts as an opaque token.  Twilio calls are
additionally protected by ``X-Twilio-Signature`` validation in production.

Endpoints
---------
GET  /api/v1/voice/twiml/outbound/{attempt_id}
    TwiML: returned to Twilio/Telnyx when the contact answers.
    Puts the contact in a conference room and plays hold music.

GET  /api/v1/voice/twiml/agent/{attempt_id}
    TwiML: returned to Twilio/Telnyx for the agent leg.
    Agent WebRTC / SIP client joins the same conference room.

GET  /api/v1/voice/ncco/{attempt_id}
    NCCO JSON: returned to Vonage when the contact answers.

GET  /api/v1/voice/hold
    Hold-music TwiML (looping).

POST /api/v1/voice/status/{attempt_id}
    Status callback from Twilio.

POST /api/v1/voice/vonage/event/{attempt_id}
    Event webhook from Vonage.

POST /api/v1/voice/telnyx/event/{attempt_id}
    Event webhook from Telnyx.

POST /api/v1/voice/at/event/{attempt_id}
    Session event callback from Africa's Talking.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AttemptStatus, Campaign, CampaignAttempt, Contact, VoiceConnector, CallRecording

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice-twiml"])


# ─── TwiML helpers ─────────────────────────────────────────────────────────────

def _xml(content: str) -> Response:
    return Response(content=content, media_type="application/xml")


_HOLD_MUSIC_URL = (
    "https://com.twilio.sounds.music.s3.amazonaws.com/MARKOVICHAMP.mp3"
)

# SA ECTA / CPA: disclose recording at the start of every call
_RECORDING_DISCLOSURE = (
    "This call may be recorded for quality and training purposes."
)


# ─── Twilio / Telnyx TwiML endpoints ─────────────────────────────────────────

@router.get("/twiml/outbound/{attempt_id}", include_in_schema=False)
async def outbound_twiml(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """TwiML Twilio/Telnyx fetches when the contact answers the outbound call.

    Discloses recording (CPA / ECTA) then bridges the contact into a named
    conference room.  The agent joins via ``/twiml/agent/{attempt_id}``.
    Recording status callback fires to ``/api/v1/voice/recording/twilio/{attempt_id}``
    when Twilio finishes processing.
    """
    result = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    attempt = result.scalar_one_or_none()

    if not attempt:
        xml = (
            "<Response>"
            "<Say>Sorry, this call is no longer available.</Say>"
            "</Response>"
        )
        return _xml(xml)

    base = str(request.base_url).rstrip("/")
    recording_cb = f"{base}/api/v1/voice/recording/twilio/{attempt_id}"
    room = f"outbound-{attempt_id}"
    xml = (
        "<Response>"
        f"<Say voice=\"alice\" language=\"en-ZA\">{_RECORDING_DISCLOSURE}</Say>"
        "<Say voice=\"alice\" language=\"en-ZA\">Please hold while we connect your call.</Say>"
        f"<Record action=\"#\" maxLength=\"7200\""
        f" recordingStatusCallback=\"{recording_cb}\""
        f" recordingStatusCallbackMethod=\"POST\""
        f" playBeep=\"false\""
        f" trim=\"do-not-trim\" />"
        "<Dial>"
        f"<Conference beep=\"false\""
        f" startConferenceOnEnter=\"false\""
        f" endConferenceOnExit=\"true\""
        f" record=\"record-from-start\""
        f" recordingStatusCallback=\"{recording_cb}\""
        f" recordingStatusCallbackMethod=\"POST\""
        f" waitUrl=\"/api/v1/voice/hold\">"
        f"{room}"
        "</Conference>"
        "</Dial>"
        "</Response>"
    )
    return _xml(xml)


@router.get("/twiml/agent/{attempt_id}", include_in_schema=False)
async def agent_twiml(attempt_id: uuid.UUID):
    """TwiML for the agent WebRTC / SIP leg — joins the same conference room."""
    room = f"outbound-{attempt_id}"
    xml = (
        "<Response>"
        "<Dial>"
        f"<Conference beep=\"false\""
        f" startConferenceOnEnter=\"true\""
        f" endConferenceOnExit=\"true\">"
        f"{room}"
        "</Conference>"
        "</Dial>"
        "</Response>"
    )
    return _xml(xml)


@router.get("/hold", include_in_schema=False)
async def hold_music():
    """TwiML hold music — loops until conference starts."""
    xml = (
        "<Response>"
        f"<Play loop=\"0\">{_HOLD_MUSIC_URL}</Play>"
        "</Response>"
    )
    return _xml(xml)


# ─── Twilio status callback ────────────────────────────────────────────────────

_TWILIO_STATUS_MAP: dict[str, AttemptStatus | None] = {
    "initiated":  None,
    "ringing":    None,
    "answered":   AttemptStatus.CONNECTED,
    "completed":  AttemptStatus.COMPLETED,
    "busy":       AttemptStatus.BUSY,
    "no-answer":  AttemptStatus.NO_ANSWER,
    "failed":     AttemptStatus.FAILED,
    "canceled":   AttemptStatus.FAILED,
}


async def _push_call_event(
    agent_id: uuid.UUID,
    attempt_id: uuid.UUID,
    new_status: AttemptStatus,
    contact_id: uuid.UUID | None,
    connected_at: datetime | None,
    db: AsyncSession,
) -> None:
    """Forward call lifecycle events to the agent's WebSocket. Deferred import avoids circular refs."""
    try:
        from app.routers.chat_ws import manager as _ws_m  # noqa: PLC0415
        agent_str  = str(agent_id)
        attempt_str = str(attempt_id)

        if new_status == AttemptStatus.CONNECTED:
            contact_name: str | None = None
            contact_phone: str | None = None
            if contact_id:
                c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
                c = c_res.scalar_one_or_none()
                if c:
                    contact_name  = getattr(c, "full_name", None)
                    contact_phone = getattr(c, "phone", None)
            await _ws_m.send_agent(agent_str, {
                "type":          "call_connected",
                "attempt_id":    attempt_str,
                "contact_name":  contact_name,
                "contact_phone": contact_phone,
                "connected_at":  (connected_at or datetime.utcnow()).isoformat() + "Z",
            })

        elif new_status in (
            AttemptStatus.COMPLETED, AttemptStatus.BUSY,
            AttemptStatus.NO_ANSWER, AttemptStatus.FAILED,
        ):
            await _ws_m.send_agent(agent_str, {
                "type":       "call_ended",
                "attempt_id": attempt_str,
                "reason":     new_status.value,
            })

    except Exception as _ws_err:
        _log.warning("_push_call_event agent=%s: %s", agent_id, _ws_err)


async def _update_attempt(
    attempt_id: uuid.UUID,
    new_status: AttemptStatus,
    duration_seconds: int | None,
    db: AsyncSession,
) -> None:
    result = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        return

    attempt.status = new_status
    now = datetime.utcnow()

    if new_status == AttemptStatus.CONNECTED and not attempt.connected_at:
        attempt.connected_at = now

    terminal = new_status in (
        AttemptStatus.COMPLETED,
        AttemptStatus.BUSY,
        AttemptStatus.NO_ANSWER,
        AttemptStatus.FAILED,
    )
    if terminal:
        if not attempt.ended_at:
            attempt.ended_at = now
        if duration_seconds is not None and not attempt.handle_duration:
            attempt.handle_duration = duration_seconds

    # Capture before commit — session expires objects on commit
    _agent_id   = attempt.agent_id
    _contact_id = attempt.contact_id
    _attempt_id = attempt.id
    _connected  = attempt.connected_at

    await db.commit()

    if _agent_id:
        await _push_call_event(
            agent_id=_agent_id,
            attempt_id=_attempt_id,
            new_status=new_status,
            contact_id=_contact_id,
            connected_at=_connected,
            db=db,
        )


@router.post("/status/{attempt_id}", include_in_schema=False)
async def twilio_status_callback(
    attempt_id: uuid.UUID,
    request: Request,
    CallStatus: str = Form(...),
    CallDuration: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Twilio POSTs here whenever the call status changes.

    Validates ``X-Twilio-Signature`` when the connector's auth_token is present.
    Loads the attempt → campaign → voice connector to retrieve the token used for
    signing, then invokes Twilio's RequestValidator before processing the update.
    """
    # ── Twilio signature validation ───────────────────────────────────────
    sig = request.headers.get("X-Twilio-Signature", "")
    if sig:
        att_row = await db.execute(
            select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
        )
        att = att_row.scalar_one_or_none()
        if att and att.campaign_id:
            camp_row = await db.execute(
                select(Campaign).where(Campaign.id == att.campaign_id)
            )
            camp = camp_row.scalar_one_or_none()
            conn_id_str = (camp.settings or {}).get("voice_connector_id") if camp else None
            if conn_id_str:
                try:
                    vc_row = await db.execute(
                        select(VoiceConnector).where(
                            VoiceConnector.id == uuid.UUID(str(conn_id_str))
                        )
                    )
                    vc = vc_row.scalar_one_or_none()
                    if vc and vc.auth_token:
                        try:
                            from twilio.request_validator import RequestValidator
                            form_data = dict(await request.form())
                            validator = RequestValidator(vc.auth_token)
                            if not validator.validate(str(request.url), form_data, sig):
                                raise HTTPException(
                                    status_code=403,
                                    detail="Invalid Twilio signature",
                                )
                        except ImportError:
                            _log.warning(
                                "twilio package not available — signature validation skipped"
                            )
                except (ValueError, Exception) as _e:
                    _log.warning("Signature validation: connector lookup failed: %s", _e)

    new_status = _TWILIO_STATUS_MAP.get(CallStatus.lower())
    if new_status is None:
        # Push ringing notification to the agent without updating attempt status
        if CallStatus.lower() in ("ringing", "initiated"):
            _ring_res = await db.execute(
                select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
            )
            _ring_att = _ring_res.scalar_one_or_none()
            if _ring_att and _ring_att.agent_id:
                try:
                    from app.routers.chat_ws import manager as _ws_m  # noqa: PLC0415
                    await _ws_m.send_agent(str(_ring_att.agent_id), {
                        "type":       "call_ringing",
                        "attempt_id": str(attempt_id),
                    })
                except Exception as _re:
                    _log.warning("call_ringing WS push failed: %s", _re)
        return {"ok": True}

    duration = int(CallDuration) if CallDuration and CallDuration.isdigit() else None
    await _update_attempt(attempt_id, new_status, duration, db)
    return {"ok": True}


# ─── Vonage event webhook ──────────────────────────────────────────────────────

_VONAGE_STATUS_MAP: dict[str, AttemptStatus | None] = {
    "ringing":    None,
    "answered":   AttemptStatus.CONNECTED,
    "completed":  AttemptStatus.COMPLETED,
    "busy":       AttemptStatus.BUSY,
    "unanswered": AttemptStatus.NO_ANSWER,
    "timeout":    AttemptStatus.NO_ANSWER,
    "failed":     AttemptStatus.FAILED,
    "rejected":   AttemptStatus.FAILED,
    "cancelled":  AttemptStatus.FAILED,
    "machine":    AttemptStatus.NO_ANSWER,
}


@router.post("/vonage/event/{attempt_id}", include_in_schema=False)
async def vonage_event(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Vonage posts call events here."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    status = body.get("status", "")
    new_status = _VONAGE_STATUS_MAP.get(status)
    if new_status is None:
        return {"ok": True}

    duration = body.get("duration")
    duration_s = int(duration) if duration else None
    await _update_attempt(attempt_id, new_status, duration_s, db)
    return {"ok": True}


@router.get("/ncco/{attempt_id}", include_in_schema=False)
async def vonage_ncco(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """NCCO Vonage fetches when the contact answers.

    Returns Connect action to a named conversation (equivalent of Twilio conference).
    Includes SA CPA / ECTA recording disclosure.
    """
    result = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    attempt = result.scalar_one_or_none()

    if not attempt:
        ncco = [{"action": "talk", "text": "Sorry, this call is no longer available.", "language": "en-ZA"}]
        return JSONResponse(ncco)

    base = str(request.base_url).rstrip("/")
    recording_cb = f"{base}/api/v1/voice/recording/vonage/{attempt_id}"
    ncco = [
        {
            "action": "talk",
            "text": f"{_RECORDING_DISCLOSURE} Please hold while we connect your call.",
            "language": "en-ZA",
            "style": 0,
        },
        {
            "action": "conversation",
            "name": f"outbound-{attempt_id}",
            "startOnEnter": False,
            "endOnExit": True,
            "record": True,
            "recordingEventUrl": [recording_cb],
            "eventUrl": [f"{base}/api/v1/voice/vonage/event/{attempt_id}"],
            "musicOnHoldUrl": [_HOLD_MUSIC_URL],
        },
    ]
    return JSONResponse(ncco)


# ─── Telnyx event webhook ──────────────────────────────────────────────────────

_TELNYX_STATUS_MAP: dict[str, AttemptStatus | None] = {
    "call.initiated":    None,
    "call.ringing":      None,
    "call.answered":     AttemptStatus.CONNECTED,
    "call.hangup":       AttemptStatus.COMPLETED,
    "call.machine.detection.ended": None,
}


@router.post("/telnyx/event/{attempt_id}", include_in_schema=False)
async def telnyx_event(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Telnyx posts call control events here."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    event_type = body.get("data", {}).get("event_type", "")
    payload    = body.get("data", {}).get("payload", {})
    new_status = _TELNYX_STATUS_MAP.get(event_type)

    # Recording completed event
    if event_type == "call.recording.saved":
        rec_url      = payload.get("public_url") or payload.get("url")
        rec_duration = payload.get("duration_millis")
        rec_id       = payload.get("recording_id") or payload.get("id")
        if rec_url:
            from app.routers.recordings import _create_recording_row, _schedule_download  # noqa: PLC0415
            rec = await _create_recording_row(
                db=db,
                attempt_id=attempt_id,
                provider="telnyx",
                leg="merged",
                provider_recording_id=str(rec_id) if rec_id else None,
                provider_url=rec_url,
                duration_seconds=int(rec_duration / 1000) if rec_duration else None,
            )
            await _schedule_download(rec.id, rec_url, provider="telnyx", auth=None)
        return {"ok": True}

    if new_status is None:
        # Treat hangup cause as failed if not normal
        if event_type == "call.hangup":
            hangup_cause = payload.get("hangup_cause", "")
            if hangup_cause not in ("normal_clearing", ""):
                new_status = AttemptStatus.FAILED
        if new_status is None:
            return {"ok": True}

    await _update_attempt(attempt_id, new_status, None, db)
    return {"ok": True}


# ─── Africa's Talking session event ───────────────────────────────────────────

_AT_STATUS_MAP: dict[str, AttemptStatus | None] = {
    "Ringing":    None,
    "Active":     AttemptStatus.CONNECTED,
    "Transferring": None,
    "Completed":  AttemptStatus.COMPLETED,
    "Cancelled":  AttemptStatus.FAILED,
    "Failed":     AttemptStatus.FAILED,
    "MissedCall": AttemptStatus.NO_ANSWER,
}


@router.post("/at/event/{attempt_id}", include_in_schema=False)
async def africastalking_event(
    attempt_id: uuid.UUID,
    isActive: str = Form(None),
    status: str = Form(None),
    duration: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Africa's Talking posts session events here as form data."""
    # AT uses isActive=0 on hangup; map to Completed when present
    resolved_status = status or ("Completed" if isActive == "0" else None)
    if not resolved_status:
        return {"ok": True}

    new_status = _AT_STATUS_MAP.get(resolved_status)
    if new_status is None:
        return {"ok": True}

    duration_s = int(duration) if duration and duration.isdigit() else None
    await _update_attempt(attempt_id, new_status, duration_s, db)
    return {"ok": True}


# ─── Agent TwiML App callback (browser SDK) ───────────────────────────────────

@router.post("/twiml/agent-connect", include_in_schema=False)
async def agent_twiml_connect(attempt_id: str = Form(...)):
    """Twilio posts here (via TwiML App) when the agent browser SDK connects.

    The browser SDK passes ``attempt_id`` via ``device.connect({params: ...})``.
    Returns TwiML that puts the agent into the named conference for that attempt.
    """
    room = f"outbound-{attempt_id}"
    xml = (
        "<Response>"
        "<Dial>"
        f"<Conference beep=\"false\""
        f" startConferenceOnEnter=\"true\""
        f" endConferenceOnExit=\"true\">"
        f"{room}"
        "</Conference>"
        "</Dial>"
        "</Response>"
    )
    return _xml(xml)


# ─── Agent WebRTC credentials (provider-agnostic) ─────────────────────────────
#
# Returns a standard shape that the front-end voice_device.js interprets:
#   { provider, webrtc_supported, sdk_url, credentials, identity, ttl }
#
# webrtc_supported=True  → browser SDK available; credentials contains opaque blob
# webrtc_supported=False → provider requires desk/softphone; show fallback banner
#
# Provider matrix:
#   twilio            → Twilio.Device (twilio/voice-sdk CDN)
#   telnyx            → TelnyxRTC (@telnyx/webrtc CDN, SIP credentials)
#   3cx | asterisk | freeswitch | generic
#                     → SIP/desk phone fallback (no browser SDK)
#   vonage | africastalking
#                     → REST-only; no browser SDK

_TWILIO_SDK_URL  = "https://sdk.twilio.com/js/voice/2.10/twilio.min.js"
_TELNYX_SDK_URL  = "https://cdn.jsdelivr.net/npm/@telnyx/webrtc@latest/lib/bundle/index.js"

@router.get("/agent-credentials", summary="Agent WebRTC credentials (provider-agnostic)")
async def get_agent_credentials(
    connector_id: uuid.UUID = Query(..., description="Voice connector ID"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return provider-specific credentials for the agent's in-browser softphone.

    The response shape is identical regardless of provider so the frontend
    ``WzVoiceDevice`` wrapper can pick the right SDK at runtime.
    """
    vc_row = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = vc_row.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")

    provider = (vc.provider or "generic").lower()
    identity = f"agent-{current_user.id}"

    # ── Twilio ──────────────────────────────────────────────────────────────
    if provider == "twilio":
        missing = [f for f in ("account_sid", "api_key", "api_secret", "twiml_app_sid")
                   if not getattr(vc, f, None)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Connector missing fields for Twilio WebRTC: {', '.join(missing)}",
            )
        try:
            from twilio.jwt.access_token import AccessToken
            from twilio.jwt.access_token.grants import VoiceGrant
            token = AccessToken(vc.account_sid, vc.api_key, vc.api_secret,
                                identity=identity, ttl=3600)
            token.add_grant(VoiceGrant(
                outgoing_application_sid=vc.twiml_app_sid,
                incoming_allow=False,
            ))
            return {
                "provider": "twilio",
                "webrtc_supported": True,
                "sdk_url": _TWILIO_SDK_URL,
                "credentials": {"token": token.to_jwt()},
                "identity": identity,
                "ttl": 3600,
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="twilio package not installed")

    # ── Telnyx ──────────────────────────────────────────────────────────────
    if provider == "telnyx":
        # Telnyx WebRTC uses SIP credentials: login = sip_domain username, password = api_secret
        # Set api_key = SIP username (e.g. "+15555550100@sip.telnyx.com")
        # Set api_secret = SIP password
        missing = [f for f in ("api_key", "api_secret") if not getattr(vc, f, None)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Connector missing fields for Telnyx WebRTC: {', '.join(missing)}",
            )
        return {
            "provider": "telnyx",
            "webrtc_supported": True,
            "sdk_url": _TELNYX_SDK_URL,
            "credentials": {
                "login": vc.api_key,
                "password": vc.api_secret,
            },
            "identity": identity,
            "ttl": 3600,
        }

    # ── All other providers — no browser WebRTC SDK available ───────────────
    # Agents answer on desk phone / softphone; platform places the call via API.
    _PROVIDER_LABELS = {
        "vonage":         "Vonage",
        "africastalking": "Africa's Talking",
        "3cx":            "3CX",
        "asterisk":       "Asterisk",
        "freeswitch":     "FreeSWITCH",
        "generic":        "Generic SIP",
    }
    return {
        "provider": provider,
        "webrtc_supported": False,
        "sdk_url": None,
        "credentials": None,
        "identity": identity,
        "ttl": 0,
        "message": (
            f"{_PROVIDER_LABELS.get(provider, provider)} does not support in-browser calling. "
            "The system will place the call via the API and connect your desk phone."
        ),
    }


# ── Legacy alias — keep old path working ──────────────────────────────────────
@router.get("/agent-token", include_in_schema=False)
async def get_agent_token_legacy(
    connector_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Deprecated — use /agent-credentials instead."""
    return await get_agent_credentials(connector_id=connector_id, db=db, current_user=current_user)


# ─── 3CX call event webhook ────────────────────────────────────────────────────

_3CX_STATUS_MAP: dict[str, AttemptStatus | None] = {
    "Ringing":      None,                    # outbound — we already know it was placed
    "CallAnswered": AttemptStatus.CONNECTED,
    "CallEnded":    AttemptStatus.COMPLETED, # refined below when duration == 0
    "Missed":       AttemptStatus.NO_ANSWER,
    "Failed":       AttemptStatus.FAILED,
}


@router.post("/3cx/event", include_in_schema=False)
async def threecx_event(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """3CX CRM webhook — receives all call events from the connected 3CX instance.

    3CX does not support per-call webhook URLs; the URL is configured once in
    Settings → CRM Integration on the 3CX management console.  WizzardChat
    identifies the matching attempt by the 3CX call_id stored in
    ``CampaignAttempt.notes``.
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    event    = body.get("event", "")
    call_id  = str(body.get("callid", "")).strip()
    duration = int(body.get("duration", 0) or 0)

    new_status = _3CX_STATUS_MAP.get(event)
    if event == "CallEnded" and duration == 0:
        new_status = AttemptStatus.NO_ANSWER  # rang but nobody answered

    if new_status is None or not call_id:
        return {"ok": True}

    result = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.notes.like(f"%{call_id}%"))
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        _log.warning("3cx_event: no attempt found for call_id=%s event=%s", call_id, event)
        return {"ok": True}

    await _update_attempt(attempt.id, new_status, duration or None, db)
    return {"ok": True}


# ─── FreeSWITCH IVR callback + event webhook ───────────────────────────────────

_FS_FAILED_CAUSES = frozenset({
    "CALL_REJECTED", "NO_ROUTE_DESTINATION", "DESTINATION_OUT_OF_ORDER",
    "NORMAL_TEMPORARY_FAILURE", "RECOVERY_ON_TIMER_EXPIRE",
})
_FS_NO_ANSWER_CAUSES = frozenset({"NO_ANSWER", "ORIGINATOR_CANCEL", "USER_BUSY"})


@router.post("/freeswitch/ivr/{attempt_id}", include_in_schema=False)
async def freeswitch_ivr(
    attempt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Called by FreeSWITCH mod_httapi when an outbound call is answered.

    The attempt UUID is baked into the URL via ``origination_uuid`` in the
    ``bgapi originate`` command, so the channel UUID equals the attempt_id.
    We mark the attempt as CONNECTED and return a simple hold XML that keeps
    the contact on the line while the agent is connected.
    """
    await _update_attempt(attempt_id, AttemptStatus.CONNECTED, None, db)
    xml = (
        "<document type=\"xml/freeswitch-httapi\">"
        "<work>"
        "<pause milliseconds=\"30000\"/>"
        "</work>"
        "</document>"
    )
    from fastapi.responses import Response
    return Response(content=xml, media_type="text/xml")


@router.post("/freeswitch/event/{attempt_id}", include_in_schema=False)
async def freeswitch_event(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """FreeSWITCH hangup / state event endpoint.

    FreeSWITCH can be directed here via the ``api_hangup_hook`` channel
    variable or via mod_httapi hangup handling.  Accepts both form-encoded
    and JSON payloads.
    """
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        try:
            body = await request.json()
        except Exception:
            return {"ok": False}
        event_name   = body.get("Event-Name", "")
        hangup_cause = body.get("Hangup-Cause", "")
        billsec      = body.get("variable_billsec", None)
    else:
        form         = await request.form()
        event_name   = form.get("Event-Name", "")
        hangup_cause = form.get("Hangup-Cause", "")
        billsec      = form.get("variable_billsec", None)

    if event_name not in ("CHANNEL_ANSWER", "CHANNEL_HANGUP_COMPLETE"):
        return {"ok": True}

    if event_name == "CHANNEL_ANSWER":
        await _update_attempt(attempt_id, AttemptStatus.CONNECTED, None, db)
        return {"ok": True}

    # CHANNEL_HANGUP_COMPLETE
    if hangup_cause in _FS_FAILED_CAUSES:
        new_status = AttemptStatus.FAILED
    elif hangup_cause in _FS_NO_ANSWER_CAUSES:
        new_status = AttemptStatus.NO_ANSWER
    else:
        new_status = AttemptStatus.COMPLETED  # NORMAL_CLEARING

    duration_s = int(billsec) if billsec and str(billsec).isdigit() else None
    await _update_attempt(attempt_id, new_status, duration_s, db)
    return {"ok": True}


# ─── Asterisk ARI event (HTTP mode) ───────────────────────────────────────────

_ARI_CHANNEL_STATES: dict[str, AttemptStatus | None] = {
    "Up":   AttemptStatus.CONNECTED,
    "Busy": AttemptStatus.BUSY,
}
# Asterisk hangup cause codes (Q.850)
_ARI_BUSY_CAUSES    = frozenset({17})           # User Busy
_ARI_NO_ANS_CAUSES  = frozenset({18, 19})       # No User Response / No Answer
_ARI_NORMAL_CAUSES  = frozenset({16})           # Normal Clearing


@router.post("/asterisk/event/{attempt_id}", include_in_schema=False)
async def asterisk_event(
    attempt_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Asterisk ARI HTTP event endpoint (alternative to the WebSocket stream).

    The ``attempt_id`` is passed as ``appArgs`` in the ``POST /ari/channels``
    originate call and is echoed back in every Stasis event.

    Configure Asterisk to POST ARI events to::

        POST https://your-host/api/v1/voice/asterisk/event/{attempt_id}
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    event_type = body.get("type", "")
    new_status: AttemptStatus | None = None

    if event_type == "ChannelStateChange":
        state = body.get("channel", {}).get("state", "")
        new_status = _ARI_CHANNEL_STATES.get(state)

    elif event_type in ("ChannelHangupRequest", "StasisEnd"):
        cause = int(body.get("cause", 16))
        if cause in _ARI_BUSY_CAUSES:
            new_status = AttemptStatus.BUSY
        elif cause in _ARI_NO_ANS_CAUSES:
            new_status = AttemptStatus.NO_ANSWER
        elif cause in _ARI_NORMAL_CAUSES:
            new_status = AttemptStatus.COMPLETED
        else:
            new_status = AttemptStatus.FAILED

    if new_status is None:
        return {"ok": True}

    await _update_attempt(attempt_id, new_status, None, db)
    return {"ok": True}

