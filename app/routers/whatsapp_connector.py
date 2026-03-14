"""WhatsApp Connector router — CRUD for WhatsApp Business API connectors.

Each connector record represents one WhatsApp Business Account (WABA) or
phone number with its provider credentials.  The inbound webhook at
``POST /api/v1/inbound/whatsapp`` (inbound_router.py) uses the connector's
``id`` to route messages to the correct ``start_whatsapp`` flow entry node.

Supported providers
-------------------
- ``meta_cloud``  — Meta Cloud API (formerly Facebook Cloud API)
- ``twilio``      — Twilio Messaging (WhatsApp channel)
- ``360dialog``   — 360dialog BSP
- ``vonage``      — Vonage Messages API
- ``generic``     — Any provider that can POST to the inbound webhook

Webhook URL to give to your provider
-------------------------------------
``POST https://<your-domain>/api/v1/inbound/whatsapp``

Body: ``{connector_id, from_number, display_name, message_body, media_url, message_id}``

For Meta Cloud API verification (GET challenge), configure your HTTPS public
URL in the Meta App Dashboard and set ``verify_token`` on this connector.
The verify endpoint is at ``GET /api/v1/whatsapp-connectors/{id}/verify``.

Endpoints
---------
GET    /api/v1/whatsapp-connectors          — list
POST   /api/v1/whatsapp-connectors          — create
GET    /api/v1/whatsapp-connectors/{id}     — get one
PUT    /api/v1/whatsapp-connectors/{id}     — update
DELETE /api/v1/whatsapp-connectors/{id}     — delete
GET    /api/v1/whatsapp-connectors/{id}/webhook-info — return webhook config for the provider
GET    /api/v1/whatsapp-connectors/{id}/verify       — Meta webhook verification challenge
POST   /api/v1/whatsapp-connectors/{id}/verify       — Meta webhook event receiver (proxy to inbound)
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import WhatsAppConnector
from app.schemas import (
    WhatsAppConnectorCreate,
    WhatsAppConnectorOut,
    WhatsAppConnectorUpdate,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/whatsapp-connectors",
    tags=["whatsapp-connectors"],
    dependencies=[Depends(get_current_user)],
)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[WhatsAppConnectorOut])
async def list_whatsapp_connectors(db: AsyncSession = Depends(get_db)):
    """List all WhatsApp connectors."""
    result = await db.execute(
        select(WhatsAppConnector).order_by(WhatsAppConnector.name)
    )
    return result.scalars().all()


@router.post("", response_model=WhatsAppConnectorOut, status_code=201)
async def create_whatsapp_connector(
    body: WhatsAppConnectorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new WhatsApp connector."""
    wc = WhatsAppConnector(**body.model_dump())
    db.add(wc)
    await db.flush()
    await db.refresh(wc)
    await db.commit()
    return wc


@router.get("/{connector_id}", response_model=WhatsAppConnectorOut)
async def get_whatsapp_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get one WhatsApp connector by ID."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc:
        raise HTTPException(status_code=404, detail="WhatsApp connector not found")
    return wc


@router.put("/{connector_id}", response_model=WhatsAppConnectorOut)
async def update_whatsapp_connector(
    connector_id: uuid.UUID,
    body: WhatsAppConnectorUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a WhatsApp connector."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc:
        raise HTTPException(status_code=404, detail="WhatsApp connector not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(wc, field, val)
    await db.flush()
    await db.refresh(wc)
    await db.commit()
    return wc


@router.delete("/{connector_id}", status_code=204)
async def delete_whatsapp_connector(
    connector_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a WhatsApp connector."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc:
        raise HTTPException(status_code=404, detail="WhatsApp connector not found")
    await db.delete(wc)
    await db.commit()


# ─── Webhook info helper ───────────────────────────────────────────────────────

@router.get("/{connector_id}/webhook-info", summary="Get webhook configuration for the provider")
async def webhook_info(connector_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the webhook URL and verify token to configure in your WhatsApp provider dashboard."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc:
        raise HTTPException(status_code=404, detail="WhatsApp connector not found")

    base = str(request.base_url).rstrip("/")
    return {
        "provider": wc.provider,
        "inbound_webhook_url": f"{base}/api/v1/inbound/whatsapp",
        "meta_verify_url": f"{base}/api/v1/whatsapp-connectors/{connector_id}/verify",
        "verify_token": wc.verify_token,
        "connector_id": str(connector_id),
        "instructions": {
            "meta_cloud": (
                "1. In your Meta App Dashboard, go to WhatsApp → Configuration. "
                "2. Set Callback URL to the meta_verify_url above. "
                "3. Set Verify Token to the verify_token value. "
                "4. Subscribe to the 'messages' webhook field. "
                "5. Configure your BSP or use the Meta Cloud API to forward messages to inbound_webhook_url."
            ),
            "twilio": (
                "In Twilio Console → Messaging → Senders → your WhatsApp number, "
                "set the inbound webhook URL to inbound_webhook_url with method POST."
            ),
            "360dialog": (
                "In the 360dialog Hub, set your webhook URL to inbound_webhook_url."
            ),
            "generic": (
                "Configure your provider to POST to inbound_webhook_url with body: "
                "{connector_id, from_number, display_name, message_body, media_url, message_id}"
            ),
        }.get(wc.provider, "Configure your provider to POST to inbound_webhook_url."),
    }


# ─── Meta Cloud API webhook verification (no auth — called by Meta) ───────────

@router.get(
    "/{connector_id}/verify",
    include_in_schema=False,
    dependencies=[],  # No auth — Meta calls this
)
async def meta_verify_get(
    connector_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Meta webhook verification challenge (GET hub.challenge)."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc:
        raise HTTPException(status_code=404)

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == wc.verify_token:
        _log.info("Meta webhook verified for WhatsApp connector %s", connector_id)
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post(
    "/{connector_id}/verify",
    include_in_schema=False,
    dependencies=[],  # No auth — Meta calls this
)
async def meta_verify_post(
    connector_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive Meta Cloud API webhook events and forward to the inbound router."""
    result = await db.execute(
        select(WhatsAppConnector).where(WhatsAppConnector.id == connector_id)
    )
    wc = result.scalar_one_or_none()
    if not wc or not wc.is_active:
        raise HTTPException(status_code=404)

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        return {"ok": False}

    # Extract messages from Meta Cloud API payload format
    entries = payload.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                from_number  = msg.get("from", "")          # phone — may be absent for privacy-enabled users
                from_user_id = msg.get("from_user_id", "")  # BSUID — always present from 2026-03-31
                msg_type = msg.get("type", "text")
                text = ""
                media_url = None
                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type in ("image", "audio", "video", "document"):
                    media_url = msg.get(msg_type, {}).get("url") or msg.get(msg_type, {}).get("id", "")

                # Resolve display name — match by wa_id (phone) or user_id (BSUID);
                # either may be absent when the user has enabled WhatsApp Usernames.
                contacts = value.get("contacts", [])
                contact_entry = next(
                    (
                        c for c in contacts
                        if (from_number and c.get("wa_id") == from_number)
                        or (from_user_id and c.get("user_id") == from_user_id)
                    ),
                    contacts[0] if contacts else {},
                )
                display_name = (contact_entry.get("profile") or {}).get("name", "")

                from app.routers.inbound_router import WhatsAppInboundBody
                from app.routers.inbound_router import inbound_whatsapp
                body = WhatsAppInboundBody(
                    connector_id=str(connector_id),
                    from_number=from_number,
                    from_user_id=from_user_id,
                    display_name=display_name,
                    message_body=text,
                    media_url=media_url,
                    message_id=msg.get("id"),
                )
                try:
                    await inbound_whatsapp(body)
                except Exception as exc:
                    _log.exception("Meta webhook: inbound_whatsapp error: %s", exc)

    return {"ok": True}
