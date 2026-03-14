"""Interactions router — read-only list + detail API for the Interaction History view."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from jose import JWTError, jwt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import Interaction, Connector, User, Queue, Tag
from app.schemas import InteractionDetailOut, InteractionOut

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/interactions", tags=["interactions"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label_name(obj, attr: str = "name") -> Optional[str]:
    return getattr(obj, attr, None) if obj else None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _get_segment(segments: list, seg_type: str) -> Optional[dict]:
    """Return the first segment of the given type from an interaction's segments list."""
    for s in (segments or []):
        if isinstance(s, dict) and s.get("type") == seg_type:
            return s
    return None


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/interactions/export  — trusted ETL export for WizzardWFM
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export")
async def export_interactions(
    lookback_days: int = Query(default=28, ge=1, le=365),
    limit: int = Query(default=5000, ge=1, le=10000),
    page: int = Query(default=1, ge=1),
    x_integration_key: Optional[str] = Header(default=None, alias="X-Integration-Key"),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Trusted export endpoint consumed by WizzardWFM ETL.

    Auth: X-Integration-Key matching WIZZARDWFM_INTEGRATION_KEY in .env,
    or a valid Bearer JWT (usable in development with an admin token).
    Returns rows shaped for WFM interval aggregation.
    """
    settings = get_settings()
    authed = False

    # Integration key check
    if x_integration_key and settings.wizzardwfm_integration_key:
        authed = (x_integration_key == settings.wizzardwfm_integration_key)

    # Bearer JWT fallback
    if not authed and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            authed = True
        except JWTError:
            pass

    if not authed:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — provide a valid X-Integration-Key or Bearer token",
        )

    date_from = datetime.utcnow() - timedelta(days=lookback_days)
    q = (
        select(Interaction)
        .options(
            selectinload(Interaction.connector),
            selectinload(Interaction.queue),
        )
        .where(Interaction.created_at >= date_from)
        .order_by(Interaction.created_at.desc())
    )

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.offset((page - 1) * limit).limit(limit))).scalars().all()

    items = []
    for ix in rows:
        segs = ix.segments or []
        queue_seg = _get_segment(segs, "queue")
        agent_seg = _get_segment(segs, "agent")

        # answered_at — when the agent first picked up
        answered_at = None
        if agent_seg and agent_seg.get("started_at"):
            answered_at = agent_seg["started_at"]
        elif ix.agent_id and ix.last_activity_at:
            answered_at = ix.last_activity_at.isoformat()

        # wait_time — seconds the visitor queued
        wait_time: Optional[float] = None
        if queue_seg:
            wait_time = queue_seg.get("waited_seconds")
            if wait_time is None:
                ts = _parse_iso(queue_seg.get("started_at"))
                te = _parse_iso(queue_seg.get("ended_at"))
                if ts and te:
                    wait_time = (te - ts).total_seconds()

        # handle_time — seconds agent was active (wrap_time preferred)
        handle_time: Optional[float] = ix.wrap_time
        if handle_time is None and agent_seg:
            ts = _parse_iso(agent_seg.get("started_at"))
            te = _parse_iso(agent_seg.get("ended_at"))
            if ts and te:
                handle_time = (te - ts).total_seconds()

        items.append({
            "id":            str(ix.id),
            "session_key":   ix.session_key,
            "queue_id":      str(ix.queue_id) if ix.queue_id else None,
            "queue_name":    ix.queue.name if ix.queue else None,
            "channel":       ix.connector.name if ix.connector else "chat",
            "status":        ix.status,
            "started_at":    ix.created_at.isoformat() if ix.created_at else None,
            "answered_at":   answered_at,
            "wait_time":     wait_time,
            "handle_time":   handle_time,
            "message_count": len(ix.message_log) if ix.message_log else 0,
        })

    return {"total": total, "page": page, "page_size": limit, "items": items}


def _build_detail(ix: Interaction) -> dict:
    tags = [t.name for t in (ix.tag_refs or [])]
    surveys = [
        {
            "id": str(s.id),
            "survey_name": s.survey_name,
            "responses": s.responses or {},
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        }
        for s in (ix.survey_submissions or [])
    ]
    return {
        "id": ix.id,
        "connector_id": ix.connector_id,
        "connector_name": _label_name(ix.connector),
        "session_key": ix.session_key,
        "status": ix.status,
        "visitor_metadata": ix.visitor_metadata or {},
        "flow_context": ix.flow_context or {},
        "waiting_node_id": ix.waiting_node_id,
        "queue_id": ix.queue_id,
        "queue_name": _label_name(ix.queue),
        "agent_id": ix.agent_id,
        "agent_name": (ix.agent.full_name if ix.agent and hasattr(ix.agent, "full_name") else None)
                      or (ix.agent.email if ix.agent else None),
        "message_log": ix.message_log or [],
        "segments": ix.segments or [],
        "disconnect_outcome": ix.disconnect_outcome,
        "notes": ix.notes,
        "csat_score": ix.csat_score,
        "csat_comment": ix.csat_comment,
        "csat_submitted_at": ix.csat_submitted_at.isoformat() if ix.csat_submitted_at else None,
        "nps_score": ix.nps_score,
        "nps_reason": ix.nps_reason,
        "nps_submitted_at": ix.nps_submitted_at.isoformat() if ix.nps_submitted_at else None,
        "wrap_time": ix.wrap_time,
        "created_at": ix.created_at.isoformat() if ix.created_at else None,
        "last_activity_at": ix.last_activity_at.isoformat() if ix.last_activity_at else None,
        "tags": tags,
        "survey_submissions": surveys,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/interactions  — paginated list with filters
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_interactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=200),
    status: Optional[str] = Query(default=None, description="Filter by status (e.g. 'closed', 'active')"),
    connector_id: Optional[UUID] = Query(default=None),
    agent_id: Optional[UUID] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None, description="ISO 8601 UTC start datetime"),
    date_to: Optional[datetime] = Query(default=None, description="ISO 8601 UTC end datetime"),
    search: Optional[str] = Query(default=None, description="Text search against session_key"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return a paginated list of interactions, most-recent first."""
    q = (
        select(Interaction)
        .options(
            selectinload(Interaction.connector),
            selectinload(Interaction.agent),
            selectinload(Interaction.queue),
            selectinload(Interaction.tag_refs),
        )
        .order_by(Interaction.created_at.desc())
    )

    if status:
        q = q.where(Interaction.status == status)
    if connector_id:
        q = q.where(Interaction.connector_id == connector_id)
    if agent_id:
        q = q.where(Interaction.agent_id == agent_id)
    if date_from:
        q = q.where(Interaction.created_at >= date_from)
    if date_to:
        q = q.where(Interaction.created_at <= date_to)
    if search:
        q = q.where(Interaction.session_key.ilike(f"%{search}%"))

    # Count total (same filters, no pagination)
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    q = q.offset(offset).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    items = []
    for ix in rows:
        msg_count = len(ix.message_log) if ix.message_log else 0
        visitor_page = (ix.visitor_metadata or {}).get("page_title") or (ix.visitor_metadata or {}).get("page_url") or ""
        items.append({
            "id": str(ix.id),
            "session_key": ix.session_key,
            "status": ix.status,
            "connector_id": str(ix.connector_id),
            "connector_name": _label_name(ix.connector),
            "agent_id": str(ix.agent_id) if ix.agent_id else None,
            "agent_name": (ix.agent.full_name if ix.agent and hasattr(ix.agent, "full_name") else None)
                          or (ix.agent.email if ix.agent else None),
            "queue_id": str(ix.queue_id) if ix.queue_id else None,
            "queue_name": _label_name(ix.queue),
            "disconnect_outcome": ix.disconnect_outcome,
            "csat_score": ix.csat_score,
            "nps_score": ix.nps_score,
            "visitor_page": visitor_page,
            "message_count": msg_count,
            "created_at": ix.created_at.isoformat() if ix.created_at else None,
            "last_activity_at": ix.last_activity_at.isoformat() if ix.last_activity_at else None,
            "tags": [t.name for t in (ix.tag_refs or [])],
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/interactions/filters  — dropdown data for filter bar
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/filters")
async def get_filter_options(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return connector and agent lists for the filter bar."""
    connectors = (await db.execute(
        select(Connector.id, Connector.name).order_by(Connector.name)
    )).all()
    agents = (await db.execute(
        select(User.id, User.email).order_by(User.email)
    )).all()
    return {
        "connectors": [{"id": str(c.id), "name": c.name} for c in connectors],
        "agents": [{"id": str(a.id), "name": a.email} for a in agents],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/interactions/{id}  — full detail
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{interaction_id}")
async def get_interaction(
    interaction_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return the full detail payload for one interaction."""
    ix = (await db.execute(
        select(Interaction)
        .where(Interaction.id == interaction_id)
        .options(
            selectinload(Interaction.connector),
            selectinload(Interaction.agent),
            selectinload(Interaction.queue),
            selectinload(Interaction.tag_refs),
            selectinload(Interaction.survey_submissions),
        )
    )).scalar_one_or_none()

    if not ix:
        raise HTTPException(status_code=404, detail="Interaction not found")

    return _build_detail(ix)
