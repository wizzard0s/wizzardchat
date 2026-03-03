"""Global outcome management endpoints."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Outcome
from app.schemas import OutcomeCreate, OutcomeOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/outcomes",
    tags=["outcomes"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[OutcomeOut])
async def list_outcomes(active_only: bool = False, db: AsyncSession = Depends(get_db)):
    q = select(Outcome).order_by(Outcome.label)
    if active_only:
        q = q.where(Outcome.is_active == True)
    result = await db.execute(q)
    return [OutcomeOut.model_validate(o) for o in result.scalars().all()]


@router.post("", response_model=OutcomeOut, status_code=201)
async def create_outcome(body: OutcomeCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Outcome).where(Outcome.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Outcome code '{body.code}' already exists")
    o = Outcome(**body.model_dump())
    db.add(o)
    await db.flush()
    await db.refresh(o)
    return OutcomeOut.model_validate(o)


@router.get("/{outcome_id}", response_model=OutcomeOut)
async def get_outcome(outcome_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Outcome).where(Outcome.id == outcome_id))
    o = result.scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Outcome not found")
    return OutcomeOut.model_validate(o)


@router.put("/{outcome_id}", response_model=OutcomeOut)
async def update_outcome(outcome_id: UUID, body: OutcomeCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Outcome).where(Outcome.id == outcome_id))
    o = result.scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Outcome not found")
    # Check code uniqueness if changed
    if body.code != o.code:
        clash = await db.execute(select(Outcome).where(Outcome.code == body.code))
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Outcome code '{body.code}' already exists")
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    await db.flush()
    await db.refresh(o)
    return OutcomeOut.model_validate(o)


@router.delete("/{outcome_id}", status_code=204)
async def delete_outcome(outcome_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Outcome).where(Outcome.id == outcome_id))
    o = result.scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="Outcome not found")
    await db.delete(o)
