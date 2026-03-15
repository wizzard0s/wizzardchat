"""
Webhook Subscriptions router — WizzardChat Routines.

Endpoints
---------
GET    /api/v1/webhook-subscriptions          List all subscriptions
POST   /api/v1/webhook-subscriptions          Create a subscription
GET    /api/v1/webhook-subscriptions/{id}     Get single subscription
PUT    /api/v1/webhook-subscriptions/{id}     Update a subscription
DELETE /api/v1/webhook-subscriptions/{id}     Delete a subscription

GET    /api/v1/webhook-subscriptions/{id}/deliveries   List delivery log
POST   /api/v1/webhook-subscriptions/{id}/test         Send a test ping
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User, WebhookDelivery, WebhookSubscription

router = APIRouter(prefix="/api/v1/webhook-subscriptions", tags=["routines"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WebhookSubscriptionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    url: str
    http_method: str = "POST"
    custom_headers: Optional[Dict[str, str]] = None
    event_topics: List[str]
    filter_expr: Optional[Dict[str, Any]] = None
    payload_template: Optional[Dict[str, Any]] = None
    secret: Optional[str] = None
    enabled: bool = True
    retry_max: int = 3
    timeout_seconds: int = 10

    @field_validator("http_method")
    @classmethod
    def _check_method(cls, v: str) -> str:
        v = v.upper()
        if v not in ("POST", "GET"):
            raise ValueError("http_method must be POST or GET")
        return v

    @field_validator("event_topics")
    @classmethod
    def _check_topics(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("event_topics must contain at least one topic")
        return v


class WebhookSubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    http_method: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    event_topics: Optional[List[str]] = None
    filter_expr: Optional[Dict[str, Any]] = None
    payload_template: Optional[Dict[str, Any]] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None
    retry_max: Optional[int] = None
    timeout_seconds: Optional[int] = None


class WebhookSubscriptionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    url: str
    http_method: str
    custom_headers: Optional[Dict[str, str]]
    event_topics: List[str]
    filter_expr: Optional[Dict[str, Any]]
    payload_template: Optional[Dict[str, Any]]
    secret: Optional[str]     # returned masked
    enabled: bool
    retry_max: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_masked(cls, sub: WebhookSubscription) -> "WebhookSubscriptionOut":
        data = cls.model_validate(sub)
        if data.secret:
            data.secret = "***"   # never return secret in plaintext
        return data


class WebhookDeliveryOut(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    event_id: Optional[str]
    event_topic: Optional[str]
    status: str
    attempts: int
    response_code: Optional[int]
    response_body: Optional[str]
    duration_ms: Optional[int]
    queued_at: Optional[datetime]
    last_attempt_at: Optional[datetime]
    delivered_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[WebhookSubscriptionOut])
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc())
    )
    subs = result.scalars().all()
    return [WebhookSubscriptionOut.from_orm_masked(s) for s in subs]


@router.post("", response_model=WebhookSubscriptionOut, status_code=201)
async def create_subscription(
    body: WebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub = WebhookSubscription(
        **body.model_dump(),
        created_by=current_user.id,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return WebhookSubscriptionOut.from_orm_masked(sub)


@router.get("/{sub_id}", response_model=WebhookSubscriptionOut)
async def get_subscription(
    sub_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    sub = await _get_or_404(sub_id, db)
    return WebhookSubscriptionOut.from_orm_masked(sub)


@router.put("/{sub_id}", response_model=WebhookSubscriptionOut)
async def update_subscription(
    sub_id: uuid.UUID,
    body: WebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    sub = await _get_or_404(sub_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sub, field, value)
    await db.commit()
    await db.refresh(sub)
    return WebhookSubscriptionOut.from_orm_masked(sub)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    sub = await _get_or_404(sub_id, db)
    await db.delete(sub)
    await db.commit()


# ---------------------------------------------------------------------------
# Delivery log
# ---------------------------------------------------------------------------

@router.get("/{sub_id}/deliveries", response_model=List[WebhookDeliveryOut])
async def list_deliveries(
    sub_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await _get_or_404(sub_id, db)
    q = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == sub_id)
        .order_by(desc(WebhookDelivery.queued_at))
        .limit(limit)
    )
    if status:
        q = q.where(WebhookDelivery.status == status)
    result = await db.execute(q)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Test ping
# ---------------------------------------------------------------------------

@router.post("/{sub_id}/test", status_code=202)
async def test_subscription(
    sub_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Fire a synthetic ``test.ping`` event to verify the endpoint is reachable."""
    await _get_or_404(sub_id, db)
    from app.services.event_dispatcher import dispatch
    test_payload = {
        "event":      "test.ping",
        "message":    "This is a WizzardChat Routines test delivery.",
        "sent_at":    datetime.utcnow().isoformat() + "Z",
    }
    await dispatch("test.ping", test_payload, db)
    return {"ok": True, "message": "Test ping queued"}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_or_404(sub_id: uuid.UUID, db: AsyncSession) -> WebhookSubscription:
    result = await db.execute(
        select(WebhookSubscription).where(WebhookSubscription.id == sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    return sub
