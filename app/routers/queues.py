"""Queue management endpoints."""

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.database import get_db
from app.models import Queue, User, queue_agents
from app.schemas import QueueCreate, QueueOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/queues",
    tags=["queues"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[QueueOut])
async def list_queues(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Queue).order_by(Queue.name))
    return [QueueOut.model_validate(q) for q in result.scalars().all()]


@router.post("", response_model=QueueOut, status_code=201)
async def create_queue(body: QueueCreate, db: AsyncSession = Depends(get_db)):
    q = Queue(**body.model_dump())
    db.add(q)
    await db.flush()
    await db.refresh(q)
    return QueueOut.model_validate(q)


@router.get("/{queue_id}", response_model=QueueOut)
async def get_queue(queue_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found")
    return QueueOut.model_validate(q)


@router.put("/{queue_id}", response_model=QueueOut)
async def update_queue(queue_id: UUID, body: QueueCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(q, k, v)
    await db.flush()
    await db.refresh(q)
    return QueueOut.model_validate(q)


@router.delete("/{queue_id}", status_code=204)
async def delete_queue(queue_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found")
    await db.delete(q)


@router.post("/{queue_id}/agents/{user_id}", status_code=204)
async def add_agent_to_queue(queue_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(queue_agents.insert().values(queue_id=queue_id, user_id=user_id))


@router.delete("/{queue_id}/agents/{user_id}", status_code=204)
async def remove_agent_from_queue(queue_id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(
        queue_agents.delete().where(
            (queue_agents.c.queue_id == queue_id) & (queue_agents.c.user_id == user_id)
        )
    )
