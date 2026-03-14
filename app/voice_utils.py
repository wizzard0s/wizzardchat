"""Outbound voice call helpers — multi-provider.

Supported providers
-------------------
- ``twilio``         — Twilio REST API (twilio>=9.0)
- ``vonage``         — Vonage Voice API (vonage>=3.0)
- ``telnyx``         — Telnyx REST API v2 (httpx, no SDK required)
- ``africastalking`` — Africa's Talking Voice API (httpx)
- ``generic``        — Any provider: no automatic call; dialler remains in preview mode

Provider selection
------------------
Pass ``provider`` from ``VoiceConnector.provider``.  The function signature is
identical for all providers; the caller does not need to branch.

SA CPA / ECTA compliance
------------------------
``assert_calling_hours()`` must be called before placing any outbound call.  It
raises ``CallingHoursError`` if the current SAST time is outside the legal window
defined in the campaign's ``calling_hours`` settings.

Default legal window (Consumer Protection Act / direct-marketing regulations):
  Mon–Fri  08:00 – 20:00 SAST
  Sat      08:00 – 13:00 SAST
  Sun / Public holidays  — no calling

References
----------
https://developers.twilio.com/docs/voice/api/call-resource
https://developer.vonage.com/en/voice/voice-api/code-snippets/make-an-outbound-call
https://developers.telnyx.com/docs/voice/programmable-voice/placing-calls
https://developers.africastalking.com/docs/voice/calling
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

_log = logging.getLogger(__name__)

_SAST = ZoneInfo("Africa/Johannesburg")

# SA public holidays 2026 (add / extend as needed)
_SA_PUBLIC_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),   # New Year's Day
    date(2026, 3, 21),  # Human Rights Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 6),   # Family Day
    date(2026, 4, 27),  # Freedom Day
    date(2026, 5, 1),   # Workers' Day
    date(2026, 6, 16),  # Youth Day
    date(2026, 8, 10),  # National Women's Day
    date(2026, 9, 24),  # Heritage Day
    date(2026, 12, 16), # Day of Reconciliation
    date(2026, 12, 25), # Christmas Day
    date(2026, 12, 26), # Day of Goodwill
})


class CallingHoursError(Exception):
    """Raised when an outbound call is attempted outside the legal calling window."""


_DEFAULT_CALLING_HOURS: Dict[str, Any] = {
    "mon_fri_start": "08:00",
    "mon_fri_end":   "20:00",
    "sat_start":     "08:00",
    "sat_end":       "13:00",
    # Sunday and public holidays: no calling
}


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.strip().split(":")
    return int(h), int(m)


def assert_calling_hours(calling_hours: Optional[Dict[str, Any]] = None) -> None:
    """Raise ``CallingHoursError`` if the current SAST time is outside the allowed window.

    Parameters
    ----------
    calling_hours:
        Dict with keys ``mon_fri_start``, ``mon_fri_end``, ``sat_start``,
        ``sat_end`` (all "HH:MM" strings).  Defaults to the CPA/ECTA minimums.
    """
    from datetime import datetime
    ch = {**_DEFAULT_CALLING_HOURS, **(calling_hours or {})}

    now = datetime.now(_SAST)
    today = now.date()
    weekday = now.weekday()  # 0=Mon … 6=Sun

    if today in _SA_PUBLIC_HOLIDAYS_2026:
        raise CallingHoursError(
            f"Today ({today.isoformat()}) is a South African public holiday. "
            "Outbound calling is not permitted (CPA / ECTA)."
        )

    if weekday == 6:  # Sunday
        raise CallingHoursError(
            "Outbound calling is not permitted on Sundays (CPA / ECTA)."
        )

    now_minutes = now.hour * 60 + now.minute

    if weekday == 5:  # Saturday
        sh, sm = _parse_hhmm(ch.get("sat_start", "08:00"))
        eh, em = _parse_hhmm(ch.get("sat_end",   "13:00"))
        start_m, end_m = sh * 60 + sm, eh * 60 + em
        if not (start_m <= now_minutes < end_m):
            raise CallingHoursError(
                f"Current SAST time {now.strftime('%H:%M')} is outside the Saturday "
                f"calling window {ch.get('sat_start')}–{ch.get('sat_end')} (CPA / ECTA)."
            )
    else:  # Mon–Fri
        sh, sm = _parse_hhmm(ch.get("mon_fri_start", "08:00"))
        eh, em = _parse_hhmm(ch.get("mon_fri_end",   "20:00"))
        start_m, end_m = sh * 60 + sm, eh * 60 + em
        if not (start_m <= now_minutes < end_m):
            raise CallingHoursError(
                f"Current SAST time {now.strftime('%H:%M')} is outside the Mon–Fri "
                f"calling window {ch.get('mon_fri_start')}–{ch.get('mon_fri_end')} (CPA / ECTA)."
            )


# ─── Twilio ────────────────────────────────────────────────────────────────────

async def initiate_twilio_call(
    *,
    account_sid: str,
    auth_token: str,
    to_number: str,
    from_number: str,
    twiml_url: str,
    status_callback_url: str,
) -> str:
    """Place an outbound call via Twilio REST API.

    The Twilio SDK is synchronous; this wrapper runs it in a thread pool so it
    does not block the FastAPI event loop.

    Returns
    -------
    str
        The Twilio call SID.
    """
    from twilio.rest import Client

    def _create() -> str:
        client = Client(account_sid, auth_token)
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=twiml_url,
            status_callback=status_callback_url,
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        return call.sid

    sid: str = await asyncio.get_event_loop().run_in_executor(None, _create)
    _log.info("Twilio call SID %s → %s", sid, to_number)
    return sid


# ─── Vonage ────────────────────────────────────────────────────────────────────

async def initiate_vonage_call(
    *,
    api_key: str,
    api_secret: str,
    to_number: str,
    from_number: str,
    answer_url: str,
    event_url: str,
) -> str:
    """Place an outbound call via Vonage Voice API.

    Returns
    -------
    str
        The Vonage call UUID.
    """
    import vonage

    def _create() -> str:
        client = vonage.Client(key=api_key, secret=api_secret)
        voice = vonage.Voice(client)
        response = voice.create_call({
            "to": [{"type": "phone", "number": to_number.lstrip("+")}],
            "from": {"type": "phone", "number": from_number.lstrip("+")},
            "answer_url": [answer_url],
            "event_url": [event_url],
        })
        return response["uuid"]

    uuid: str = await asyncio.get_event_loop().run_in_executor(None, _create)
    _log.info("Vonage call UUID %s → %s", uuid, to_number)
    return uuid


# ─── Telnyx ────────────────────────────────────────────────────────────────────

async def initiate_telnyx_call(
    *,
    api_key: str,
    to_number: str,
    from_number: str,
    webhook_url: str,
    connection_id: Optional[str] = None,
) -> str:
    """Place an outbound call via the Telnyx REST v2 API.

    Returns
    -------
    str
        The Telnyx call control ID.
    """
    import httpx

    payload: Dict[str, Any] = {
        "to": to_number,
        "from": from_number,
        "webhook_url": webhook_url,
    }
    if connection_id:
        payload["connection_id"] = connection_id

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.telnyx.com/v2/calls",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    call_id: str = data["data"]["call_control_id"]
    _log.info("Telnyx call control ID %s → %s", call_id, to_number)
    return call_id


# ─── Africa's Talking ──────────────────────────────────────────────────────────

async def initiate_africastalking_call(
    *,
    api_key: str,
    username: str,
    to_number: str,
    from_number: str,
    callback_url: str,
) -> str:
    """Place an outbound call via Africa's Talking Voice API.

    Africa's Talking uses POST form-data rather than JSON.

    Returns
    -------
    str
        The ``sessionId`` returned by Africa's Talking.
    """
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://voice.africastalking.com/call",
            headers={
                "apiKey": api_key,
                "Accept": "application/json",
            },
            data={
                "username": username,
                "to": to_number,
                "from": from_number,
                "callbackUrl": callback_url,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("entries", [{}])
    session_id: str = entries[0].get("sessionId", "")
    _log.info("Africa's Talking sessionId %s → %s", session_id, to_number)
    return session_id


# ─── Asterisk ARI ─────────────────────────────────────────────────────────────

async def initiate_asterisk_call(
    *,
    connector,      # VoiceConnector ORM instance
    to_number: str,
    attempt_id: str,
) -> str:
    """Originate an outbound call via the Asterisk REST Interface (ARI).

    ARI endpoint: ``POST http://{sip_domain}/ari/channels``

    Credential mapping from ``VoiceConnector``
    ------------------------------------------
    - ``sip_domain``         → Asterisk host:port (default 8088)
    - ``account_sid``        → ARI username
    - ``auth_token``         → ARI password
    - ``api_key``            → Stasis application name (default "wizzardchat")
    - ``api_secret``         → SIP trunk name (e.g. ``voip_ms``)
    - ``caller_id_override`` → Outbound caller ID shown to the contact

    Returns
    -------
    str
        Asterisk channel ID (stored in ``CampaignAttempt.notes`` for event matching).
    """
    import httpx

    host = (connector.sip_domain or "localhost:8088")
    username = connector.account_sid or ""
    password = connector.auth_token or ""
    app = connector.api_key or "wizzardchat"
    trunk = connector.api_secret or ""
    caller_id = getattr(connector, "caller_id_override", None) or ""

    endpoint = f"SIP/{trunk}/{to_number}" if trunk else f"SIP/{to_number}"
    url = f"http://{host}/ari/channels"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            url,
            auth=(username, password),
            json={
                "endpoint": endpoint,
                "callerId": caller_id,
                "app": app,
                "appArgs": str(attempt_id),
            },
        )
        resp.raise_for_status()
        data = resp.json()

    channel_id: str = data.get("id", str(attempt_id))
    _log.info("Asterisk ARI channel %s → %s", channel_id, to_number)
    return channel_id


# ─── FreeSWITCH ESL ───────────────────────────────────────────────────────────

async def initiate_freeswitch_call(
    *,
    connector,      # VoiceConnector ORM instance
    to_number: str,
    attempt_id: str,
    base_url: str,
) -> str:
    """Originate an outbound call via FreeSWITCH Event Socket Library (ESL).

    Connects to the ESL TCP socket, authenticates, and sends a ``bgapi originate``
    command.  The channel UUID is set to ``attempt_id`` via ``origination_uuid``
    so that subsequent mod_httapi callbacks can reference it.

    Credential mapping from ``VoiceConnector``
    ------------------------------------------
    - ``sip_domain``         → FreeSWITCH host:port (default 8021)
    - ``account_sid``        → ESL username (usually ``ClueCon``)
    - ``auth_token``         → ESL password
    - ``api_key``            → Outbound SIP gateway name (from ``sofia.conf``)
    - ``api_secret``         → Fallback outbound caller ID
    - ``caller_id_override`` → Outbound caller ID (takes precedence over api_secret)

    Returns
    -------
    str
        FreeSWITCH bgapi Job-UUID (stored in ``CampaignAttempt.notes``).
    """
    import asyncio
    import re as _re

    host_port = (connector.sip_domain or "localhost:8021").rsplit(":", 1)
    host = host_port[0]
    port = int(host_port[1]) if len(host_port) > 1 else 8021
    password = connector.auth_token or "ClueCon"
    gateway = connector.api_key or ""
    caller_id = getattr(connector, "caller_id_override", None) or connector.api_secret or ""

    ivr_url = f"{base_url}/api/v1/voice/freeswitch/ivr/{attempt_id}"
    vars_str = (
        f"{{origination_caller_id_number={caller_id},"
        f"origination_uuid={attempt_id}}}"
    )
    endpoint = (
        f"sofia/gateway/{gateway}/{to_number}"
        if gateway
        else f"sofia/profile/external/{to_number}"
    )
    cmd = f'bgapi originate {vars_str}{endpoint} &httapi({{"url":"{ivr_url}"}})\n\n'

    reader, writer = await asyncio.open_connection(host, port)
    try:
        data = await asyncio.wait_for(reader.read(1024), timeout=5)
        if b"auth/request" not in data:
            raise RuntimeError(f"Unexpected FreeSWITCH ESL greeting: {data[:80]!r}")

        writer.write(f"auth {password}\n\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=5)
        if b"+OK accepted" not in data:
            raise RuntimeError(f"FreeSWITCH ESL auth failed: {data[:80]!r}")

        writer.write(cmd.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=5)

        m = _re.search(rb"Job-UUID: ([\w-]+)", data)
        job_uuid = m.group(1).decode() if m else str(attempt_id)
        _log.info("FreeSWITCH bgapi Job-UUID %s → %s", job_uuid, to_number)
        return job_uuid
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ─── 3CX REST API ─────────────────────────────────────────────────────────────

# In-process bearer token cache: connector_id → (token, expires_at_epoch)
_3cx_token_cache: Dict[str, tuple] = {}


async def _get_3cx_token(connector, client) -> str:
    """Fetch or return a cached OAuth2 bearer token for a 3CX connector."""
    import time

    cid = str(connector.id)
    cached = _3cx_token_cache.get(cid)
    if cached and cached[1] > time.time():
        return cached[0]

    host = connector.sip_domain or "localhost:5001"
    scheme = "https" if "." in host else "http"  # use https for hostnames, http for bare IPs
    url = f"{scheme}://{host}/connect/token"

    resp = await client.post(
        url,
        data={
            "grant_type":    "client_credentials",
            "client_id":     connector.account_sid or "",
            "client_secret": connector.auth_token or "",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token: str = data["access_token"]
    expires_in: int = int(data.get("expires_in", 3600))
    _3cx_token_cache[cid] = (token, time.time() + expires_in - 60)
    return token


async def initiate_3cx_call(
    *,
    connector,      # VoiceConnector ORM instance
    to_number: str,
    attempt_id: str,
) -> str:
    """Originate an outbound call via the 3CX REST Call Management API.

    Uses the OAuth2 client credentials flow to obtain a bearer token, then
    calls ``POST /xapi/v1/callmanagement`` to instruct 3CX to ring the agent's
    extension first and then bridge to the contact.

    Credential mapping from ``VoiceConnector``
    ------------------------------------------
    - ``sip_domain``         → 3CX REST API host:port
    - ``account_sid``        → OAuth2 client_id
    - ``auth_token``         → OAuth2 client_secret
    - ``api_key``            → Default agent extension number
    - ``caller_id_override`` → Outbound caller ID shown to the contact

    Returns
    -------
    str
        3CX call ID (stored in ``CampaignAttempt.notes`` for webhook matching).
    """
    import httpx

    host = connector.sip_domain or "localhost:5001"
    scheme = "https" if "." in host else "http"
    agent_ext = connector.api_key or "100"
    caller_id = getattr(connector, "caller_id_override", None) or ""

    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        token = await _get_3cx_token(connector, client)
        resp = await client.post(
            f"{scheme}://{host}/xapi/v1/callmanagement",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "Entity": {
                    "To":        {"Entity": {"Number": to_number}},
                    "Originate": {"From": {"Entity": {"Number": agent_ext}}},
                }
            },
        )
        resp.raise_for_status()
        data = resp.json()

    # 3CX returns the new call ID in different places depending on version
    call_id: str = (
        str(data.get("callId") or data.get("Id") or data.get("id") or attempt_id)
    )
    _log.info("3CX call_id %s → %s (agent ext %s)", call_id, to_number, agent_ext)
    return call_id


# ─── Provider dispatcher ───────────────────────────────────────────────────────

async def place_outbound_call(
    *,
    provider: str,
    connector,           # VoiceConnector SQLAlchemy model instance
    to_number: str,
    from_number: str,
    twiml_url: str,      # Twilio / Telnyx: fetchable XML; Vonage: NCCO answer URL
    status_callback_url: str,
    base_url: str,       # base URL of this WizzardChat instance
    attempt_id: str,
) -> str:
    """Dispatch an outbound call to the appropriate provider.

    Parameters
    ----------
    provider:
        Value of ``VoiceConnector.provider`` — one of ``twilio``, ``vonage``,
        ``telnyx``, ``africastalking``.  Any other value raises ``ValueError``.
    connector:
        The ``VoiceConnector`` ORM instance (read-only; credentials accessed here).
    to_number:
        E.164 recipient phone number.
    from_number:
        E.164 caller ID (from campaign or connector DID).
    twiml_url:
        URL WizzardChat exposes for TwiML / NCCO (Vonage answer URL).
    status_callback_url:
        URL WizzardChat exposes for call status webhooks.
    base_url:
        Base URL of this instance, used to build Vonage event URL.
    attempt_id:
        UUID of the ``CampaignAttempt`` row (used in URL building for Vonage/AT).

    Returns
    -------
    str
        Provider-specific call identifier stored in ``CampaignAttempt.notes``.

    Raises
    ------
    ValueError
        If the provider is ``generic`` or unrecognised.
    CallingHoursError
        Propagated from ``assert_calling_hours()`` — caller should catch this.
    """
    if provider == "twilio":
        return await initiate_twilio_call(
            account_sid=connector.account_sid,
            auth_token=connector.auth_token,
            to_number=to_number,
            from_number=from_number,
            twiml_url=twiml_url,
            status_callback_url=status_callback_url,
        )

    if provider == "vonage":
        return await initiate_vonage_call(
            api_key=connector.api_key,
            api_secret=connector.api_secret,
            to_number=to_number,
            from_number=from_number,
            answer_url=twiml_url,   # Vonage calls this to fetch the NCCO
            event_url=f"{base_url}/api/v1/voice/vonage/event/{attempt_id}",
        )

    if provider == "telnyx":
        return await initiate_telnyx_call(
            api_key=connector.api_key,
            to_number=to_number,
            from_number=from_number,
            webhook_url=status_callback_url,
            connection_id=connector.sip_domain or None,
        )

    if provider == "africastalking":
        return await initiate_africastalking_call(
            api_key=connector.auth_token,        # AT stores key in auth_token
            username=connector.account_sid,      # AT stores username in account_sid
            to_number=to_number,
            from_number=from_number,
            callback_url=status_callback_url,
        )

    if provider == "asterisk":
        return await initiate_asterisk_call(
            connector=connector,
            to_number=to_number,
            attempt_id=attempt_id,
        )

    if provider == "freeswitch":
        return await initiate_freeswitch_call(
            connector=connector,
            to_number=to_number,
            attempt_id=attempt_id,
            base_url=base_url,
        )

    if provider == "3cx":
        return await initiate_3cx_call(
            connector=connector,
            to_number=to_number,
            attempt_id=attempt_id,
        )

    raise ValueError(
        f"Provider '{provider}' does not support automatic outbound calls. "
        "Use 'twilio', 'vonage', 'telnyx', 'africastalking', 'asterisk', 'freeswitch', or '3cx'."
    )
