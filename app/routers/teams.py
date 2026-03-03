"""Team management endpoints."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Team, User, team_members
from app.schemas import TeamCreate, TeamUpdate, TeamOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/teams",
    tags=["teams"],
    dependencies=[Depends(get_current_user)],
)


def _with_members():
    return selectinload(Team.members)


@router.get("", response_model=List[TeamOut])
async def list_teams(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).options(_with_members()).order_by(Team.name))
    return [TeamOut.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(body: TeamCreate, db: AsyncSession = Depends(get_db)):
    t = Team(**body.model_dump())
    db.add(t)
    await db.flush()
    await db.refresh(t)
    # reload with members relationship
    result = await db.execute(
        select(Team).options(_with_members()).where(Team.id == t.id)
    )
    t = result.scalar_one()
    await db.commit()
    return TeamOut.model_validate(t)


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Team).options(_with_members()).where(Team.id == team_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamOut.model_validate(t)


@router.put("/{team_id}", response_model=TeamOut)
async def update_team(team_id: UUID, body: TeamUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Team).options(_with_members()).where(Team.id == team_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    await db.flush()
    await db.refresh(t)
    result = await db.execute(
        select(Team).options(_with_members()).where(Team.id == team_id)
    )
    t = result.scalar_one()
    await db.commit()
    return TeamOut.model_validate(t)


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.delete(t)
    await db.commit()


@router.post("/{team_id}/members/{user_id}", status_code=204)
async def add_member(team_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    # verify both exist
    team_row = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team_row:
        raise HTTPException(status_code=404, detail="Team not found")
    user_row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    # Remove from any existing team first (one team per user rule)
    await db.execute(
        team_members.delete().where(team_members.c.user_id == user_id)
    )
    # Insert into the new team
    await db.execute(team_members.insert().values(team_id=team_id, user_id=user_id))
    await db.commit()


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_member(team_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(
        team_members.delete().where(
            (team_members.c.team_id == team_id) & (team_members.c.user_id == user_id)
        )
    )
    await db.commit()

