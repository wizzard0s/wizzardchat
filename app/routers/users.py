"""User management endpoints."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Campaign
from app.schemas import UserCreate, UserUpdate, UserOut, CampaignOut
from app.auth import hash_password, get_current_user, require_permission

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],
)

# ── Helper: base query that always excludes system accounts ──
_visible_users = select(User).where(User.is_system_account == False)  # noqa: E712


@router.get("", response_model=List[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(_visible_users.order_by(User.full_name))
    return [UserOut.model_validate(u) for u in result.scalars().all()]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        _visible_users.where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("users.edit")),
):
    result = await db.execute(
        _visible_users.where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = body.model_dump(exclude_unset=True)
    # Hash password if provided
    if "password" in data:
        pwd = data.pop("password")
        if pwd:
            user.hashed_password = hash_password(pwd)
    for field, value in data.items():
        setattr(user, field, value)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users.delete")),
):
    if str(current_user.id) == str(user_id):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(
        _visible_users.where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)


# ── Campaign assignment (via campaign.agents JSONB) ──────────────────────────

class CampaignAssignBody(BaseModel):
    campaign_ids: List[str] = []


@router.get("/{user_id}/campaigns", response_model=List[CampaignOut])
async def get_user_campaigns(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return all campaigns where this user appears in the agents JSONB list."""
    uid = str(user_id)
    result = await db.execute(select(Campaign))
    campaigns = result.scalars().all()
    assigned = [c for c in campaigns if uid in (c.agents or [])]
    return [CampaignOut.model_validate(c) for c in assigned]


@router.put("/{user_id}/campaigns", status_code=204)
async def set_user_campaigns(
    user_id: UUID,
    body: CampaignAssignBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("users.edit")),
):
    """Sync this user's campaign assignments.

    Adds user_id to agents of every campaign in body.campaign_ids,
    and removes it from every campaign NOT in the list.
    """
    uid = str(user_id)
    target_ids = set(body.campaign_ids)

    result = await db.execute(select(Campaign))
    campaigns = result.scalars().all()

    for campaign in campaigns:
        agents: list = list(campaign.agents or [])
        in_agents = uid in agents
        should_be = campaign.id in target_ids or str(campaign.id) in target_ids

        if should_be and not in_agents:
            agents.append(uid)
            campaign.agents = agents
        elif not should_be and in_agents:
            agents.remove(uid)
            campaign.agents = agents

    await db.flush()
