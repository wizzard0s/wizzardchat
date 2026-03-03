"""Campaign management endpoints."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, CampaignStatus, User
from app.schemas import CampaignCreate, CampaignOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    return [CampaignOut.model_validate(c) for c in result.scalars().all()]


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = Campaign(**body.model_dump(), created_by=user.id)
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignOut.model_validate(c)


@router.put("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: UUID, body: CampaignCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(c, key, val)
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.post("/{campaign_id}/start", response_model=CampaignOut)
async def start_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=400, detail=f"Cannot start campaign in {c.status} state")
    c.status = CampaignStatus.RUNNING
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = CampaignStatus.PAUSED
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = CampaignStatus.CANCELLED
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.delete(c)
