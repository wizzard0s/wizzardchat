"""Supervisor wallboard — real-time campaign, queue, and team views."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Campaign,
    ChannelType,
    Conversation,
    ConversationStatus,
    Queue,
    Team,
    User,
)

router = APIRouter(
    prefix="/api/v1/wallboard",
    tags=["wallboard"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _queue_stats(
    db: AsyncSession,
    queue_ids: list[UUID] | None = None,
) -> dict[UUID, dict]:
    """Return per-queue live stats dict keyed by queue UUID."""
    WAITING = ConversationStatus.WAITING
    ALIVE = [ConversationStatus.ACTIVE, ConversationStatus.ON_HOLD, ConversationStatus.WRAP_UP]

    stmt_w = (
        select(
            Conversation.queue_id,
            func.count().label("cnt"),
            func.min(Conversation.started_at).label("oldest"),
        )
        .where(Conversation.status == WAITING)
        .group_by(Conversation.queue_id)
    )
    stmt_a = (
        select(
            Conversation.queue_id,
            func.count().label("cnt"),
        )
        .where(Conversation.status.in_(ALIVE))
        .group_by(Conversation.queue_id)
    )
    if queue_ids is not None:
        stmt_w = stmt_w.where(Conversation.queue_id.in_(queue_ids))
        stmt_a = stmt_a.where(Conversation.queue_id.in_(queue_ids))

    w_rows = (await db.execute(stmt_w)).all()
    a_rows = (await db.execute(stmt_a)).all()

    stats: dict[UUID, dict] = {}
    now = _utcnow()
    for row in w_rows:
        oldest = row.oldest
        wait_secs = int((now - oldest).total_seconds()) if oldest else 0
        stats.setdefault(row.queue_id, {})["waiting"] = row.cnt
        stats[row.queue_id]["longest_wait_seconds"] = wait_secs
    for row in a_rows:
        stats.setdefault(row.queue_id, {})["active"] = row.cnt

    return stats


def _queue_payload(q: Queue, stats: dict) -> dict:
    st = stats.get(q.id, {})
    waiting = st.get("waiting", 0)
    longest = st.get("longest_wait_seconds", 0)
    threshold = q.sla_threshold or 30
    return {
        "id": str(q.id),
        "name": q.name,
        "channel": q.channel.value if q.channel else "chat",
        "color": q.color or "#fd7e14",
        "strategy": q.strategy.value if q.strategy else "round_robin",
        "sla_threshold": threshold,
        "waiting": waiting,
        "active": st.get("active", 0),
        "agents_count": len(q.agents),
        "longest_wait_seconds": longest,
        "sla_ok": longest < threshold,
    }


# ── Campaign list ─────────────────────────────────────────────────────────────

@router.get("/campaigns")
async def wallboard_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(Campaign.name))
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status.value if c.status else "draft",
            "color": c.color or "#0d6efd",
            "queue_ids": c.queues or [],
            "agent_ids": c.agents or [],
        }
        for c in result.scalars().all()
    ]


# ── Campaign detail ───────────────────────────────────────────────────────────

@router.get("/campaign/{campaign_id}")
async def wallboard_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Queues: either linked via FK or listed in campaign.queues JSONB
    jsonb_ids: list[UUID] = []
    for raw in campaign.queues or []:
        try:
            jsonb_ids.append(UUID(str(raw)))
        except ValueError:
            pass

    q_result = await db.execute(
        select(Queue)
        .where(
            (Queue.campaign_id == campaign_id)
            | (Queue.id.in_(jsonb_ids) if jsonb_ids else Queue.id == None)  # noqa: E711
        )
        .options(selectinload(Queue.agents))
    )
    queues = q_result.scalars().unique().all()
    queue_ids = [q.id for q in queues]

    stat_map = await _queue_stats(db, queue_ids)

    # Agents: from campaign.agents JSONB + queue rosters
    agent_ids_set: set[UUID] = set()
    for raw in campaign.agents or []:
        try:
            agent_ids_set.add(UUID(str(raw)))
        except ValueError:
            pass
    for q in queues:
        agent_ids_set.update(u.id for u in q.agents)

    agents: list[User] = []
    if agent_ids_set:
        a_result = await db.execute(select(User).where(User.id.in_(agent_ids_set)))
        agents = a_result.scalars().all()

    # Active / wrap-up convs per agent
    agent_active_map: dict[UUID, int] = defaultdict(int)
    agent_wrapup_map: dict[UUID, int] = defaultdict(int)
    if agent_ids_set:
        ac_result = await db.execute(
            select(Conversation.agent_id, Conversation.status, func.count().label("cnt"))
            .where(
                Conversation.agent_id.in_(agent_ids_set),
                Conversation.status.in_(
                    [ConversationStatus.ACTIVE, ConversationStatus.WRAP_UP]
                ),
            )
            .group_by(Conversation.agent_id, Conversation.status)
        )
        for row in ac_result.all():
            if row.status == ConversationStatus.WRAP_UP:
                agent_wrapup_map[row.agent_id] = row.cnt
            else:
                agent_active_map[row.agent_id] = row.cnt

    def _agent_status(u: User) -> str:
        if not u.is_online:
            return "offline"
        if agent_wrapup_map[u.id] > 0 and agent_active_map[u.id] == 0:
            return "wrap_up"
        if agent_active_map[u.id] > 0 or agent_wrapup_map[u.id] > 0:
            return "busy"
        return "available"

    queue_list = [_queue_payload(q, stat_map) for q in queues]
    agent_list = [
        {
            "id": str(u.id),
            "full_name": u.full_name,
            "username": u.username,
            "is_online": u.is_online,
            "status": _agent_status(u),
            "active_convs": agent_active_map[u.id] + agent_wrapup_map[u.id],
            "wrap_up_convs": agent_wrapup_map[u.id],
            "max_concurrent": u.max_concurrent_chats or 5,
        }
        for u in agents
    ]

    total_waiting = sum(q["waiting"] for q in queue_list)
    total_active = sum(q["active"] for q in queue_list)
    agents_online = sum(1 for a in agent_list if a["is_online"])

    return {
        "campaign": {
            "id": str(campaign.id),
            "name": campaign.name,
            "status": campaign.status.value if campaign.status else "draft",
            "color": campaign.color or "#0d6efd",
        },
        "summary": {
            "total_waiting": total_waiting,
            "total_active": total_active,
            "agents_online": agents_online,
            "agents_total": len(agent_list),
            "queues_count": len(queue_list),
            "sla_breached_queues": sum(1 for q in queue_list if not q["sla_ok"]),
        },
        "queues": queue_list,
        "agents": agent_list,
    }


# ── Global queues view ────────────────────────────────────────────────────────

@router.get("/queues")
async def wallboard_queues(
    campaign_id: Optional[UUID] = Query(None),
    channel: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Queue).options(selectinload(Queue.agents))

    if campaign_id:
        c_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        campaign = c_result.scalar_one_or_none()
        jsonb_ids: list[UUID] = []
        for raw in (campaign.queues if campaign else []) or []:
            try:
                jsonb_ids.append(UUID(str(raw)))
            except ValueError:
                pass
        stmt = stmt.where(
            (Queue.campaign_id == campaign_id)
            | (Queue.id.in_(jsonb_ids) if jsonb_ids else Queue.id == None)  # noqa: E711
        )

    if channel:
        try:
            stmt = stmt.where(Queue.channel == ChannelType(channel))
        except ValueError:
            pass

    q_result = await db.execute(stmt.order_by(Queue.name))
    queues = q_result.scalars().unique().all()
    stat_map = await _queue_stats(db, [q.id for q in queues])

    return [_queue_payload(q, stat_map) for q in queues]


# ── Teams list ────────────────────────────────────────────────────────────────

@router.get("/teams")
async def wallboard_teams(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Team).options(selectinload(Team.members)).order_by(Team.name)
    )
    teams = result.scalars().unique().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "member_count": len(t.members),
            "online_count": sum(1 for m in t.members if m.is_online),
        }
        for t in teams
    ]


# ── Team detail ───────────────────────────────────────────────────────────────

@router.get("/team/{team_id}")
async def wallboard_team(
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Team)
        .where(Team.id == team_id)
        .options(
            selectinload(Team.members).selectinload(User.queues)
        )
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    member_ids = [m.id for m in team.members]

    agent_active: dict[UUID, int] = defaultdict(int)
    agent_wrapup: dict[UUID, int] = defaultdict(int)
    if member_ids:
        conv_result = await db.execute(
            select(Conversation.agent_id, Conversation.status, func.count().label("cnt"))
            .where(
                Conversation.agent_id.in_(member_ids),
                Conversation.status.in_(
                    [ConversationStatus.ACTIVE, ConversationStatus.WRAP_UP]
                ),
            )
            .group_by(Conversation.agent_id, Conversation.status)
        )
        for row in conv_result.all():
            if row.status == ConversationStatus.WRAP_UP:
                agent_wrapup[row.agent_id] = row.cnt
            else:
                agent_active[row.agent_id] = row.cnt

    def _member_status(m: User) -> str:
        if not m.is_online:
            return "offline"
        if agent_wrapup[m.id] > 0 and agent_active[m.id] == 0:
            return "wrap_up"
        if agent_active[m.id] > 0 or agent_wrapup[m.id] > 0:
            return "busy"
        return "available"

    members = [
        {
            "id": str(m.id),
            "full_name": m.full_name,
            "username": m.username,
            "role": m.role.value if m.role else "agent",
            "is_online": m.is_online,
            "status": _member_status(m),
            "active_convs": agent_active[m.id] + agent_wrapup[m.id],
            "wrap_up_convs": agent_wrapup[m.id],
            "max_concurrent": m.max_concurrent_chats or 5,
            "queues": [q.name for q in m.queues],
        }
        for m in team.members
    ]
    members.sort(key=lambda x: (not x["is_online"], x["full_name"]))

    return {
        "team": {
            "id": str(team.id),
            "name": team.name,
            "description": team.description or "",
        },
        "summary": {
            "total": len(members),
            "online": sum(1 for m in members if m["is_online"]),
            "busy": sum(1 for m in members if m["active_convs"] > 0),
        },
        "members": members,
    }
