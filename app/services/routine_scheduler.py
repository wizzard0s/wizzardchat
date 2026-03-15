"""
APScheduler-backed routine scheduler — WizzardChat Routines engine.

Loads all enabled RoutineSchedule rows from the DB on startup and registers
each as an APScheduler CronTrigger job (Africa/Johannesburg timezone by default).

On each tick it fires ``dispatch("routine.tick", {...})`` which goes through
the standard webhook delivery pipeline.

Dynamic management:  ``add_schedule``, ``update_schedule``, and
``remove_schedule`` allow the webhook_subscriptions router to keep the
scheduler in sync when schedules are created/updated/deleted via the API
without restarting the process.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session
from app.models import RoutineSchedule

_log = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

async def start_scheduler() -> None:
    """Load all enabled schedules and start the APScheduler instance."""
    sched = get_scheduler()
    if sched.running:
        return

    async with async_session() as db:
        result = await db.execute(
            select(RoutineSchedule).where(RoutineSchedule.enabled.is_(True))
        )
        schedules = result.scalars().all()

    for s in schedules:
        _register_job(sched, s)

    sched.start()
    _log.info("RoutineScheduler started with %d active schedule(s)", len(schedules))


async def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        _log.info("RoutineScheduler stopped")


# ---------------------------------------------------------------------------
# APScheduler job management
# ---------------------------------------------------------------------------

def _job_id(schedule_id: str) -> str:
    return f"routine_{schedule_id}"


def _register_job(sched: AsyncIOScheduler, schedule: RoutineSchedule) -> None:
    """Register or replace a cron job for a RoutineSchedule."""
    job_id = _job_id(str(schedule.id))

    # Remove existing job if any
    existing = sched.get_job(job_id)
    if existing:
        existing.remove()

    try:
        trigger = CronTrigger.from_crontab(schedule.cron_expression,
                                           timezone=schedule.timezone or "Africa/Johannesburg")
    except Exception as exc:
        _log.error("Invalid cron expression for schedule %s '%s': %s",
                   schedule.id, schedule.cron_expression, exc)
        return

    sched.add_job(
        _tick,
        trigger=trigger,
        id=job_id,
        args=[str(schedule.id)],
        name=schedule.name,
        replace_existing=True,
        misfire_grace_time=300,
    )
    _log.debug("Registered routine schedule: %s (%s)", schedule.name, schedule.cron_expression)


# ---------------------------------------------------------------------------
# Tick handler — called by APScheduler
# ---------------------------------------------------------------------------

async def _tick(schedule_id: str) -> None:
    """Fire ``routine.tick`` event for a schedule, then update last_run_at."""
    from app.services.event_dispatcher import dispatch  # local import to avoid circular

    async with async_session() as db:
        result = await db.execute(
            select(RoutineSchedule).where(RoutineSchedule.id == uuid.UUID(schedule_id))
        )
        schedule = result.scalar_one_or_none()
        if not schedule or not schedule.enabled:
            return

        now = datetime.utcnow()
        event_data = {
            "event":       "routine.tick",
            "schedule_id": schedule_id,
            "schedule_name": schedule.name,
            "run_at":      now.isoformat() + "Z",
            "custom_data": schedule.custom_data or {},
        }

        await dispatch("routine.tick", event_data, db)
        schedule.last_run_at = now
        await db.commit()

    _log.info("Routine tick fired: %s (%s)", schedule.name, schedule_id)


# ---------------------------------------------------------------------------
# Dynamic add / update / remove called from the CRUD router
# ---------------------------------------------------------------------------

def add_schedule(schedule: RoutineSchedule) -> None:
    sched = get_scheduler()
    if sched.running:
        _register_job(sched, schedule)


def update_schedule(schedule: RoutineSchedule) -> None:
    sched = get_scheduler()
    if sched.running:
        if schedule.enabled:
            _register_job(sched, schedule)
        else:
            remove_schedule(str(schedule.id))


def remove_schedule(schedule_id: str) -> None:
    sched = get_scheduler()
    if sched.running:
        job = sched.get_job(_job_id(schedule_id))
        if job:
            job.remove()
            _log.debug("Removed routine schedule: %s", schedule_id)
