"""Voice Connector router — CRUD for inbound telephony connectors.

Each connector record represents one telephony trunk or API account with its
provider credentials.  The inbound webhook at ``POST /api/v1/inbound/voice``
(inbound_router.py) uses the connector's ``id`` to route calls to the correct
``start_voice`` flow entry node.

Supported providers
-------------------
- ``twilio``   — Twilio Programmable Voice
- ``vonage``   — Vonage Voice API (Nexmo)
- ``asterisk`` — Asterisk/FreeSWITCH AGI or ARI webhook
- ``generic``  — Any provider that can POST to the inbound webhook

Webhook URL to give to your provider
-------------------------------------
``POST https://<your-domain>/api/v1/inbound/voice``

Body: ``{connector_id, from_number, to_number, display_name, call_id, direction, status, recording_url}``

Endpoints
---------
GET    /api/v1/voice-connectors          — list
POST   /api/v1/voice-connectors          — create
GET    /api/v1/voice-connectors/{id}     — get one
PUT    /api/v1/voice-connectors/{id}     — update
DELETE /api/v1/voice-connectors/{id}     — delete
POST   /api/v1/voice-connectors/{id}/test        — verify credentials (SIP ping or API call)
GET    /api/v1/voice-connectors/{id}/webhook-info — return webhook config for the provider
"""

from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import VoiceConnector
from app.schemas import (
    VoiceConnectorCreate,
    VoiceConnectorOut,
    VoiceConnectorUpdate,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/voice-connectors",
    tags=["voice-connectors"],
    dependencies=[Depends(get_current_user)],
)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[VoiceConnectorOut])
async def list_voice_connectors(db: AsyncSession = Depends(get_db)):
    """List all voice connectors."""
    result = await db.execute(
        select(VoiceConnector).order_by(VoiceConnector.name)
    )
    return result.scalars().all()


@router.post("", response_model=VoiceConnectorOut, status_code=201)
async def create_voice_connector(
    body: VoiceConnectorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new voice connector."""
    vc = VoiceConnector(**body.model_dump())
    db.add(vc)
    await db.flush()
    await db.refresh(vc)
    await db.commit()
    return vc


@router.get("/{connector_id}", response_model=VoiceConnectorOut)
async def get_voice_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get one voice connector by ID."""
    result = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")
    return vc


@router.put("/{connector_id}", response_model=VoiceConnectorOut)
async def update_voice_connector(
    connector_id: uuid.UUID,
    body: VoiceConnectorUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a voice connector."""
    result = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(vc, field, val)
    await db.flush()
    await db.refresh(vc)
    await db.commit()
    return vc


@router.delete("/{connector_id}", status_code=204)
async def delete_voice_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a voice connector."""
    result = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")
    await db.delete(vc)
    await db.commit()


# ─── Test / credential verification ───────────────────────────────────────────

@router.post("/{connector_id}/test", summary="Test voice connector credentials")
async def test_voice_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify the connector credentials.

    For Twilio: makes a lightweight API call to fetch the account details.
    For Vonage: fetches balance using key/secret.
    For other providers: returns a reminder to test manually via SIP / provider portal.
    """
    result = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")

    if vc.provider == "twilio":
        try:
            import httpx
            auth = (vc.account_sid, vc.auth_token)
            url = f"https://api.twilio.com/2010-04-01/Accounts/{vc.account_sid}.json"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, auth=auth)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "provider": "twilio", "friendly_name": data.get("friendly_name"), "status": data.get("status")}
            return {"ok": False, "provider": "twilio", "status_code": resp.status_code, "detail": resp.text}
        except Exception as exc:
            return {"ok": False, "provider": "twilio", "error": str(exc)}

    if vc.provider == "vonage":
        try:
            import httpx
            url = "https://rest.nexmo.com/account/get-balance"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"api_key": vc.api_key, "api_secret": vc.api_secret})
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "provider": "vonage", "balance": data.get("value"), "auto_reload": data.get("autoReload")}
            return {"ok": False, "provider": "vonage", "status_code": resp.status_code, "detail": resp.text}
        except Exception as exc:
            return {"ok": False, "provider": "vonage", "error": str(exc)}

    return {
        "ok": None,
        "provider": vc.provider,
        "message": "Automatic testing is not supported for this provider. Verify credentials in your provider portal.",
    }


# ─── Webhook info helper ───────────────────────────────────────────────────────

@router.get("/{connector_id}/webhook-info", summary="Get webhook configuration for the provider")
async def webhook_info(connector_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the webhook URL to configure in your telephony provider dashboard."""
    result = await db.execute(
        select(VoiceConnector).where(VoiceConnector.id == connector_id)
    )
    vc = result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=404, detail="Voice connector not found")

    base = str(request.base_url).rstrip("/")
    inbound_url = f"{base}/api/v1/inbound/voice"

    instructions = {
        "twilio": (
            "In Twilio Console → Phone Numbers → your number, "
            "set the Voice webhook (HTTP POST) to the inbound_webhook_url above."
        ),
        "vonage": (
            "In Vonage Dashboard → Your Applications → your Voice app, "
            "set the Answer URL (POST) to the inbound_webhook_url above."
        ),
        "asterisk": (
            "In your Asterisk/FreeSWITCH dialplan or ARI config, "
            "POST to inbound_webhook_url on an incoming call with the expected body."
        ),
        "generic": (
            "Configure your provider to POST to inbound_webhook_url with body: "
            "{connector_id, from_number, to_number, display_name, call_id, direction, status, recording_url}"
        ),
    }

    return {
        "provider": vc.provider,
        "inbound_webhook_url": inbound_url,
        "connector_id": str(connector_id),
        "did_numbers": vc.did_numbers or [],
        "sip_domain": vc.sip_domain,
        "instructions": instructions.get(
            vc.provider,
            "Configure your provider to POST to inbound_webhook_url.",
        ),
    }
