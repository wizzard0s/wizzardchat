"""Office Hours – CRUD for named operating-hours groups with weekly schedule and exclusions."""

from datetime import date as DateType
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OfficeHoursGroup, OfficeHoursSchedule, OfficeHoursExclusion
from app.schemas import (
    OfficeHoursGroupCreate, OfficeHoursGroupUpdate, OfficeHoursGroupOut,
    OfficeHoursScheduleIn, OfficeHoursScheduleOut,
    OfficeHoursExclusionCreate, OfficeHoursExclusionUpdate, OfficeHoursExclusionOut,
    DAY_NAMES,
)
from app.auth import get_current_user, require_permission

router = APIRouter(
    prefix="/api/v1/office-hours",
    tags=["office-hours"],
    dependencies=[Depends(get_current_user)],
)

# ── helpers ───────────────────────────────────────────────────────────────────

_LOAD_FULL = [
    selectinload(OfficeHoursGroup.schedule),
    selectinload(OfficeHoursGroup.exclusions),
]


def _build_group_out(grp: OfficeHoursGroup) -> OfficeHoursGroupOut:
    return OfficeHoursGroupOut(
        id=grp.id,
        name=grp.name,
        description=grp.description,
        timezone=grp.timezone,
        is_active=grp.is_active,
        created_at=grp.created_at,
        schedule=[
            OfficeHoursScheduleOut(
                id=s.id,
                day_of_week=s.day_of_week,
                day_name=DAY_NAMES[s.day_of_week],
                is_open=s.is_open,
                open_time=s.open_time,
                close_time=s.close_time,
            )
            for s in sorted(grp.schedule, key=lambda s: s.day_of_week)
        ],
        exclusions=[
            OfficeHoursExclusionOut.model_validate(e)
            for e in sorted(grp.exclusions, key=lambda e: e.date)
        ],
    )


async def _get_group_or_404(group_id: UUID, db: AsyncSession) -> OfficeHoursGroup:
    grp = (await db.execute(
        select(OfficeHoursGroup).options(*_LOAD_FULL).where(OfficeHoursGroup.id == group_id)
    )).scalar_one_or_none()
    if grp is None:
        raise HTTPException(404, "Office hours group not found")
    return grp


# ── Groups CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=List[OfficeHoursGroupOut],
            dependencies=[Depends(require_permission("office_hours.view"))])
async def list_groups(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    q = select(OfficeHoursGroup).options(*_LOAD_FULL).order_by(OfficeHoursGroup.name)
    if active_only:
        q = q.where(OfficeHoursGroup.is_active == True)
    groups = (await db.execute(q)).scalars().all()
    return [_build_group_out(g) for g in groups]


@router.post("", response_model=OfficeHoursGroupOut, status_code=201,
             dependencies=[Depends(require_permission("office_hours.create"))])
async def create_group(body: OfficeHoursGroupCreate, db: AsyncSession = Depends(get_db)):
    clash = (await db.execute(
        select(OfficeHoursGroup).where(OfficeHoursGroup.name == body.name)
    )).scalar_one_or_none()
    if clash:
        raise HTTPException(409, f"Office hours group '{body.name}' already exists")

    grp = OfficeHoursGroup(**body.model_dump())
    db.add(grp)
    await db.flush()

    # Seed a default 7-day schedule (Mon–Fri open 08:00–17:00, Sat/Sun closed)
    for dow in range(7):
        is_weekday = dow < 5
        db.add(OfficeHoursSchedule(
            group_id=grp.id,
            day_of_week=dow,
            is_open=is_weekday,
            open_time="08:00",
            close_time="17:00",
        ))

    await db.commit()
    return _build_group_out(await _get_group_or_404(grp.id, db))


@router.get("/{group_id}", response_model=OfficeHoursGroupOut,
            dependencies=[Depends(require_permission("office_hours.view"))])
async def get_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    return _build_group_out(await _get_group_or_404(group_id, db))


@router.put("/{group_id}", response_model=OfficeHoursGroupOut,
            dependencies=[Depends(require_permission("office_hours.edit"))])
async def update_group(group_id: UUID, body: OfficeHoursGroupUpdate, db: AsyncSession = Depends(get_db)):
    grp = await _get_group_or_404(group_id, db)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(grp, field, val)
    await db.commit()
    return _build_group_out(await _get_group_or_404(group_id, db))


@router.delete("/{group_id}", status_code=204,
               dependencies=[Depends(require_permission("office_hours.delete"))])
async def delete_group(group_id: UUID, db: AsyncSession = Depends(get_db)):
    grp = await _get_group_or_404(group_id, db)
    await db.delete(grp)
    await db.commit()


# ── Weekly Schedule ───────────────────────────────────────────────────────────

@router.put("/{group_id}/schedule", response_model=List[OfficeHoursScheduleOut],
            dependencies=[Depends(require_permission("office_hours.edit"))])
async def set_schedule(
    group_id: UUID,
    entries: List[OfficeHoursScheduleIn],
    db: AsyncSession = Depends(get_db),
):
    """Bulk upsert: send an entry for every day you want to change (or all 7)."""
    if len(set(e.day_of_week for e in entries)) != len(entries):
        raise HTTPException(400, "Duplicate day_of_week values in request")
    for e in entries:
        if not 0 <= e.day_of_week <= 6:
            raise HTTPException(400, f"day_of_week must be 0–6, got {e.day_of_week}")

    # Load existing rows for this group
    existing = {
        row.day_of_week: row
        for row in (await db.execute(
            select(OfficeHoursSchedule).where(OfficeHoursSchedule.group_id == group_id)
        )).scalars().all()
    }

    updated = []
    for entry in entries:
        row = existing.get(entry.day_of_week)
        if row:
            row.is_open = entry.is_open
            row.open_time = entry.open_time
            row.close_time = entry.close_time
        else:
            row = OfficeHoursSchedule(
                group_id=group_id,
                day_of_week=entry.day_of_week,
                is_open=entry.is_open,
                open_time=entry.open_time,
                close_time=entry.close_time,
            )
            db.add(row)
        updated.append(row)

    await db.commit()
    for row in updated:
        await db.refresh(row)

    return [
        OfficeHoursScheduleOut(
            id=row.id,
            day_of_week=row.day_of_week,
            day_name=DAY_NAMES[row.day_of_week],
            is_open=row.is_open,
            open_time=row.open_time,
            close_time=row.close_time,
        )
        for row in sorted(updated, key=lambda r: r.day_of_week)
    ]


# ── Exclusions ────────────────────────────────────────────────────────────────

@router.get("/{group_id}/exclusions", response_model=List[OfficeHoursExclusionOut],
            dependencies=[Depends(require_permission("office_hours.view"))])
async def list_exclusions(
    group_id: UUID,
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(OfficeHoursExclusion).where(OfficeHoursExclusion.group_id == group_id).order_by(OfficeHoursExclusion.date)
    if year:
        from sqlalchemy import extract
        q = q.where(extract("year", OfficeHoursExclusion.date) == year)
    rows = (await db.execute(q)).scalars().all()
    return [OfficeHoursExclusionOut.model_validate(r) for r in rows]


@router.post("/{group_id}/exclusions", response_model=OfficeHoursExclusionOut, status_code=201,
             dependencies=[Depends(require_permission("office_hours.edit"))])
async def add_exclusion(
    group_id: UUID,
    body: OfficeHoursExclusionCreate,
    db: AsyncSession = Depends(get_db),
):
    await _get_group_or_404(group_id, db)
    clash = (await db.execute(
        select(OfficeHoursExclusion).where(
            OfficeHoursExclusion.group_id == group_id,
            OfficeHoursExclusion.date == body.date,
        )
    )).scalar_one_or_none()
    if clash:
        raise HTTPException(409, f"An exclusion for {body.date} already exists in this group")

    if body.is_open and (not body.override_open or not body.override_close):
        raise HTTPException(400, "override_open and override_close are required when is_open=True")

    excl = OfficeHoursExclusion(group_id=group_id, **body.model_dump())
    db.add(excl)
    await db.commit()
    await db.refresh(excl)
    return OfficeHoursExclusionOut.model_validate(excl)


@router.put("/{group_id}/exclusions/{excl_id}", response_model=OfficeHoursExclusionOut,
            dependencies=[Depends(require_permission("office_hours.edit"))])
async def update_exclusion(
    group_id: UUID,
    excl_id: UUID,
    body: OfficeHoursExclusionUpdate,
    db: AsyncSession = Depends(get_db),
):
    excl = (await db.execute(
        select(OfficeHoursExclusion).where(
            OfficeHoursExclusion.id == excl_id,
            OfficeHoursExclusion.group_id == group_id,
        )
    )).scalar_one_or_none()
    if not excl:
        raise HTTPException(404, "Exclusion not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(excl, field, val)

    if excl.is_open and (not excl.override_open or not excl.override_close):
        raise HTTPException(400, "override_open and override_close are required when is_open=True")

    await db.commit()
    await db.refresh(excl)
    return OfficeHoursExclusionOut.model_validate(excl)


@router.delete("/{group_id}/exclusions/{excl_id}", status_code=204,
               dependencies=[Depends(require_permission("office_hours.edit"))])
async def delete_exclusion(
    group_id: UUID,
    excl_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    excl = (await db.execute(
        select(OfficeHoursExclusion).where(
            OfficeHoursExclusion.id == excl_id,
            OfficeHoursExclusion.group_id == group_id,
        )
    )).scalar_one_or_none()
    if not excl:
        raise HTTPException(404, "Exclusion not found")
    await db.delete(excl)
    await db.commit()
