"""
Routine Schedules router — WizzardChat Routines.

Endpoints
---------
GET    /api/v1/routine-schedules          List all schedules
POST   /api/v1/routine-schedules          Create a schedule
GET    /api/v1/routine-schedules/{id}     Get single schedule
PUT    /api/v1/routine-schedules/{id}     Update a schedule
DELETE /api/v1/routine-schedules/{id}     Delete a schedule
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import RoutineSchedule, User

router = APIRouter(prefix="/api/v1/routine-schedules", tags=["routines"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RoutineScheduleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    cron_expression: str
    timezone: str = "Africa/Johannesburg"
    custom_data: Optional[Dict[str, Any]] = None
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def _check_cron(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError(
                "cron_expression must have exactly 5 fields: minute hour dom month dow"
            )
        return v.strip()


class RoutineScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    custom_data: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class RoutineScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    cron_expression: str
    timezone: str
    custom_data: Optional[Dict[str, Any]]
    enabled: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[RoutineScheduleOut])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(RoutineSchedule).order_by(RoutineSchedule.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=RoutineScheduleOut, status_code=201)
async def create_schedule(
    body: RoutineScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = RoutineSchedule(
        **body.model_dump(),
        created_by=current_user.id,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    # Register with live scheduler
    from app.services.routine_scheduler import add_schedule
    add_schedule(schedule)

    return schedule


@router.get("/{schedule_id}", response_model=RoutineScheduleOut)
async def get_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await _get_or_404(schedule_id, db)


@router.put("/{schedule_id}", response_model=RoutineScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: RoutineScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    schedule = await _get_or_404(schedule_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    await db.commit()
    await db.refresh(schedule)

    # Sync with live scheduler
    from app.services.routine_scheduler import update_schedule as sched_update
    sched_update(schedule)

    return schedule


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    schedule = await _get_or_404(schedule_id, db)
    from app.services.routine_scheduler import remove_schedule
    remove_schedule(str(schedule_id))
    await db.delete(schedule)
    await db.commit()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_or_404(schedule_id: uuid.UUID, db: AsyncSession) -> RoutineSchedule:
    result = await db.execute(
        select(RoutineSchedule).where(RoutineSchedule.id == schedule_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Routine schedule not found")
    return s
