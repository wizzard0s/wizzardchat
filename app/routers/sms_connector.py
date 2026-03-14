"""SMS Connector router — CRUD for SMS gateway connectors.

Each connector record represents one SMS gateway account with its provider
credentials.  The inbound webhook at ``POST /api/v1/inbound/sms``
(inbound_router.py) uses the connector's ``id`` to route messages to the
correct ``start_sms`` flow entry node.

Supported providers
-------------------
- ``twilio``         — Twilio Programmable Messaging
- ``vonage``         — Vonage SMS API (Nexmo)
- ``africastalking`` — Africa's Talking SMS Gateway
- ``generic``        — Any provider that can POST to the inbound webhook

Webhook URL to give to your provider
-------------------------------------
``POST https://<your-domain>/api/v1/inbound/sms``

Body: ``{connector_id, from_number, to_number, message_body, message_id}``

Endpoints
---------
GET    /api/v1/sms-connectors          — list
POST   /api/v1/sms-connectors          — create
GET    /api/v1/sms-connectors/{id}     — get one
PUT    /api/v1/sms-connectors/{id}     — update
DELETE /api/v1/sms-connectors/{id}     — delete
POST   /api/v1/sms-connectors/{id}/test        — verify credentials (balance check or test ping)
GET    /api/v1/sms-connectors/{id}/webhook-info — return webhook config for the provider
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
from app.models import SmsConnector
from app.schemas import SmsConnectorCreate, SmsConnectorOut, SmsConnectorUpdate

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sms-connectors",
    tags=["sms-connectors"],
    dependencies=[Depends(get_current_user)],
)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SmsConnectorOut])
async def list_sms_connectors(db: AsyncSession = Depends(get_db)):
    """List all SMS connectors."""
    result = await db.execute(select(SmsConnector).order_by(SmsConnector.name))
    return result.scalars().all()


@router.post("", response_model=SmsConnectorOut, status_code=201)
async def create_sms_connector(body: SmsConnectorCreate, db: AsyncSession = Depends(get_db)):
    """Create a new SMS connector."""
    sc = SmsConnector(**body.model_dump())
    db.add(sc)
    await db.flush()
    await db.refresh(sc)
    await db.commit()
    return sc


@router.get("/{connector_id}", response_model=SmsConnectorOut)
async def get_sms_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get one SMS connector by ID."""
    result = await db.execute(select(SmsConnector).where(SmsConnector.id == connector_id))
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="SMS connector not found")
    return sc


@router.put("/{connector_id}", response_model=SmsConnectorOut)
async def update_sms_connector(
    connector_id: uuid.UUID,
    body: SmsConnectorUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an SMS connector."""
    result = await db.execute(select(SmsConnector).where(SmsConnector.id == connector_id))
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="SMS connector not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(sc, field, val)
    await db.flush()
    await db.refresh(sc)
    await db.commit()
    return sc


@router.delete("/{connector_id}", status_code=204)
async def delete_sms_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete an SMS connector."""
    result = await db.execute(select(SmsConnector).where(SmsConnector.id == connector_id))
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="SMS connector not found")
    await db.delete(sc)
    await db.commit()


# ─── Test / credential verification ───────────────────────────────────────────

@router.post("/{connector_id}/test", summary="Test SMS connector credentials")
async def test_sms_connector(connector_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Verify credentials for the configured provider.

    - **twilio**: fetches account details from the Twilio REST API.
    - **vonage**: checks account balance via the Nexmo REST API.
    - **africastalking**: fetches account balance via Africa's Talking API.
    - **generic**: returns a reminder to test manually via your provider portal.
    """
    result = await db.execute(select(SmsConnector).where(SmsConnector.id == connector_id))
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="SMS connector not found")

    if sc.provider == "twilio":
        try:
            import httpx
            auth = (sc.account_sid, sc.auth_token)
            url = f"https://api.twilio.com/2010-04-01/Accounts/{sc.account_sid}.json"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, auth=auth)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "provider": "twilio", "friendly_name": data.get("friendly_name"), "status": data.get("status")}
            return {"ok": False, "provider": "twilio", "status_code": resp.status_code, "detail": resp.text}
        except Exception as exc:
            return {"ok": False, "provider": "twilio", "error": str(exc)}

    if sc.provider == "vonage":
        try:
            import httpx
            url = "https://rest.nexmo.com/account/get-balance"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"api_key": sc.api_key, "api_secret": sc.api_secret})
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "provider": "vonage", "balance": data.get("value"), "auto_reload": data.get("autoReload")}
            return {"ok": False, "provider": "vonage", "status_code": resp.status_code, "detail": resp.text}
        except Exception as exc:
            return {"ok": False, "provider": "vonage", "error": str(exc)}

    if sc.provider == "africastalking":
        try:
            import httpx
            headers = {"Accept": "application/json", "apiKey": sc.auth_token or sc.api_key or ""}
            username = sc.account_sid or "sandbox"
            url = f"https://api.africastalking.com/version1/user?username={username}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                user_data = data.get("UserData", {})
                return {"ok": True, "provider": "africastalking", "balance": user_data.get("balance")}
            return {"ok": False, "provider": "africastalking", "status_code": resp.status_code, "detail": resp.text}
        except Exception as exc:
            return {"ok": False, "provider": "africastalking", "error": str(exc)}

    return {
        "ok": None,
        "provider": sc.provider,
        "message": "Automatic testing is not supported for this provider. Verify credentials in your provider portal.",
    }


# ─── Webhook info helper ───────────────────────────────────────────────────────

@router.get("/{connector_id}/webhook-info", summary="Get webhook configuration for the provider")
async def webhook_info(connector_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the inbound webhook URL and provider-specific setup instructions."""
    result = await db.execute(select(SmsConnector).where(SmsConnector.id == connector_id))
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="SMS connector not found")

    base = str(request.base_url).rstrip("/")
    inbound_url = f"{base}/api/v1/inbound/sms"

    instructions = {
        "twilio": (
            "In the Twilio Console → Phone Numbers → your SMS number, "
            "set the Messaging webhook (HTTP POST) to the inbound_webhook_url above."
        ),
        "vonage": (
            "In Vonage Dashboard → Your Applications → your SMS app, "
            "set the Inbound URL (POST) to the inbound_webhook_url above."
        ),
        "africastalking": (
            "In the Africa's Talking Dashboard → SMS → Callback URL, "
            "set the inbound callback to the inbound_webhook_url above."
        ),
        "generic": (
            "Configure your provider to POST to inbound_webhook_url with body: "
            "{connector_id, from_number, to_number, message_body, message_id}"
        ),
    }

    return {
        "provider": sc.provider,
        "inbound_webhook_url": inbound_url,
        "connector_id": str(connector_id),
        "from_number": sc.from_number,
        "instructions": instructions.get(
            sc.provider,
            "Configure your provider to POST to inbound_webhook_url.",
        ),
    }
