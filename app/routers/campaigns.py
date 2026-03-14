"""Campaign management endpoints."""

from uuid import UUID
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, CampaignStatus, User
from app.schemas import CampaignCreate, CampaignOut
from app.auth import get_current_user, require_permission

router = APIRouter(
    prefix="/api/v1/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    import traceback, logging
    try:
        result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
        return [CampaignOut.model_validate(c) for c in result.scalars().all()]
    except Exception as exc:
        logging.getLogger("campaigns").error("list_campaigns error: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"list_campaigns error: {exc}")


def _campaign_settings(body: CampaignCreate) -> dict:
    """Merge the explicit settings dict with the typed convenience fields."""
    s = dict(body.settings or {})
    if body.voice_connector_id is not None:
        s["voice_connector_id"] = str(body.voice_connector_id)
    if body.dialler_mode is not None:
        s["dialler_mode"] = body.dialler_mode
    if body.calling_hours is not None:
        s["calling_hours"] = body.calling_hours
    return s


_SETTINGS_FIELDS = {"voice_connector_id", "dialler_mode", "calling_hours"}


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("campaigns.create")),
):
    data = body.model_dump(exclude=_SETTINGS_FIELDS)
    data["settings"] = _campaign_settings(body)
    c = Campaign(**data, created_by=user.id)
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
async def update_campaign(
    campaign_id: UUID,
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    data = body.model_dump(exclude_unset=True, exclude=_SETTINGS_FIELDS)
    data["settings"] = _campaign_settings(body)
    for key, val in data.items():
        setattr(c, key, val)
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.post("/{campaign_id}/start", response_model=CampaignOut)
async def start_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
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
async def pause_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = CampaignStatus.PAUSED
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = CampaignStatus.CANCELLED
    await db.flush()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.delete")),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.delete(c)


# ─────────────────────────── Outbound config ─────────────────────────────────

@router.get("/{campaign_id}/outbound-config")
async def get_outbound_config(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the outbound_config JSONB for a campaign."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c.outbound_config or {}


@router.put("/{campaign_id}/outbound-config")
async def save_outbound_config(
    campaign_id: UUID,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    """Replace the outbound_config JSONB for a campaign.

    Accepts any JSON object. Expected keys:
      primary_channel, fallback_channels, autodial, dialler_mode,
      wa_template_id, wa_variable_map, wa_connector_id,
      sms_template_id, sms_variable_map, sms_connector_id,
      email_template_id, email_variable_map, email_connector_id,
      voice_connector_id, calling_hours, max_attempts, retry_interval_hours
    """
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.outbound_config = body
    await db.flush()
    await db.refresh(c)
    return c.outbound_config
