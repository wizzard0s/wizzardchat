"""Agent group management endpoints.

Groups are logical collections of agents for campaign assignment.
They are independent from Teams (which control routing) and Roles (which control permissions).
A user can belong to multiple groups.
"""

from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import get_db
from app.models import AgentGroup, User, agent_group_members
from app.schemas import AgentGroupCreate, AgentGroupUpdate, AgentGroupOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/agent-groups",
    tags=["agent-groups"],
    dependencies=[Depends(get_current_user)],
)


def _with_members():
    return selectinload(AgentGroup.members)


@router.get("", response_model=List[AgentGroupOut])
async def list_groups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentGroup).options(_with_members()).order_by(AgentGroup.name)
    )
    return [AgentGroupOut.model_validate(g) for g in result.scalars().all()]


@router.post("", response_model=AgentGroupOut, status_code=201)
async def create_group(body: AgentGroupCreate, db: AsyncSession = Depends(get_db)):
    g = AgentGroup(**body.model_dump())
    db.add(g)
    await db.flush()
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == g.id)
    )
    g = result.scalar_one()
    await db.commit()
    return AgentGroupOut.model_validate(g)


@router.get("/{group_id}", response_model=AgentGroupOut)
async def get_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == group_id)
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return AgentGroupOut.model_validate(g)


@router.put("/{group_id}", response_model=AgentGroupOut)
async def update_group(group_id: UUID, body: AgentGroupUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == group_id)
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(g, field, value)
    await db.flush()
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == group_id)
    )
    g = result.scalar_one()
    await db.commit()
    return AgentGroupOut.model_validate(g)


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentGroup).where(AgentGroup.id == group_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    await db.delete(g)
    await db.commit()


@router.post("/{group_id}/members/{user_id}", status_code=204)
async def add_member(group_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    group_row = (await db.execute(select(AgentGroup).where(AgentGroup.id == group_id))).scalar_one_or_none()
    if not group_row:
        raise HTTPException(status_code=404, detail="Group not found")
    user_row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    # Insert (ignore duplicate — user may already be in this group)
    await db.execute(
        pg_insert(agent_group_members)
        .values(group_id=group_id, user_id=user_id)
        .on_conflict_do_nothing()
    )
    await db.commit()


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(group_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(
        agent_group_members.delete().where(
            (agent_group_members.c.group_id == group_id)
            & (agent_group_members.c.user_id == user_id)
        )
    )
    await db.commit()


@router.put("/{group_id}/members", response_model=AgentGroupOut)
async def set_members(group_id: UUID, body: List[UUID], db: AsyncSession = Depends(get_db)):
    """Replace the entire member list for a group in one call."""
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == group_id)
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    # Remove all existing members
    await db.execute(
        agent_group_members.delete().where(agent_group_members.c.group_id == group_id)
    )
    # Insert new members (verify each user exists)
    if body:
        users = (await db.execute(select(User).where(User.id.in_(body)))).scalars().all()
        found_ids = {u.id for u in users}
        for uid in body:
            if uid in found_ids:
                await db.execute(
                    pg_insert(agent_group_members)
                    .values(group_id=group_id, user_id=uid)
                    .on_conflict_do_nothing()
                )
    await db.flush()
    result = await db.execute(
        select(AgentGroup).options(_with_members()).where(AgentGroup.id == group_id)
    )
    g = result.scalar_one()
    await db.commit()
    return AgentGroupOut.model_validate(g)
