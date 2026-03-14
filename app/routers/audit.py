"""Audit log read endpoints — admin/super_admin only."""

from typing import Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, User
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit"],
    dependencies=[Depends(get_current_user)],
)


@router.get("")
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
):
    q = select(AuditLog).order_by(desc(AuditLog.created_at))
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)

    total_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_res.scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    # Resolve usernames in one query
    user_ids = list({r.user_id for r in rows if r.user_id})
    usernames: dict = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username, User.full_name).where(User.id.in_(user_ids)))
        for uid, uname, fname in ures.all():
            usernames[uid] = fname or uname

    items = []
    for r in rows:
        items.append({
            "id": str(r.id),
            "user_id": str(r.user_id) if r.user_id else None,
            "username": usernames.get(r.user_id) if r.user_id else "System",
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "details": r.details,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/entity-types")
async def list_entity_types(db: AsyncSession = Depends(get_db)):
    """Return distinct entity_type values for filter dropdowns."""
    res = await db.execute(
        select(AuditLog.entity_type).distinct().where(AuditLog.entity_type.isnot(None))
    )
    return sorted([r for (r,) in res.all()])


@router.get("/actions")
async def list_actions(db: AsyncSession = Depends(get_db)):
    """Return distinct action values for filter dropdowns."""
    res = await db.execute(
        select(AuditLog.action).distinct().where(AuditLog.action.isnot(None))
    )
    return sorted([r for (r,) in res.all()])
