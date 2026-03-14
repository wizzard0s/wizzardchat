"""Dashboard statistics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Conversation, ConversationStatus, Flow, FlowStatus, User

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return live counts for the dashboard stat cards and channel breakdown."""
    ACTIVE_STATUSES = [ConversationStatus.ACTIVE, ConversationStatus.WRAP_UP]
    WAITING_STATUS  = ConversationStatus.WAITING

    active_r = await db.execute(
        select(func.count()).where(Conversation.status.in_(ACTIVE_STATUSES))
    )
    active_count = active_r.scalar() or 0

    waiting_r = await db.execute(
        select(func.count()).where(Conversation.status == WAITING_STATUS)
    )
    waiting_count = waiting_r.scalar() or 0

    agents_r = await db.execute(
        select(func.count()).where(User.is_online == True)  # noqa: E712
    )
    agents_online = agents_r.scalar() or 0

    flows_r = await db.execute(
        select(func.count()).where(Flow.status == FlowStatus.ACTIVE)
    )
    active_flows = flows_r.scalar() or 0

    # Channel breakdown
    from sqlalchemy import case
    from app.models import ChannelType
    channel_r = await db.execute(
        select(Conversation.channel, func.count().label("cnt"))
        .where(Conversation.status.in_(ACTIVE_STATUSES + [WAITING_STATUS]))
        .group_by(Conversation.channel)
    )
    channel_counts = {row.channel.value if row.channel else "chat": row.cnt
                      for row in channel_r.all()}

    return {
        "active_conversations": active_count,
        "waiting_in_queue": waiting_count,
        "agents_online": agents_online,
        "active_flows": active_flows,
        "channels": {
            "voice":    channel_counts.get("voice", 0),
            "chat":     channel_counts.get("chat", 0),
            "whatsapp": channel_counts.get("whatsapp", 0),
            "app":      channel_counts.get("app", 0),
            "email":    channel_counts.get("email", 0),
            "sms":      channel_counts.get("sms", 0),
        },
    }
