"""Agent self-service endpoints — capacity query, pick-next override, etc."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, UserRole
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],
)


class CapacityOut(BaseModel):
    """Effective capacity limits for the authenticated agent."""
    omni_max: int
    channel_max_voice: int
    channel_max_chat: int
    channel_max_whatsapp: int
    channel_max_email: int
    channel_max_sms: int
    capacity_override_active: bool
    # True = agent-level override is set; False = value comes from global default
    omni_max_is_custom: bool
    channel_max_voice_is_custom: bool
    channel_max_chat_is_custom: bool
    channel_max_whatsapp_is_custom: bool
    channel_max_email_is_custom: bool
    channel_max_sms_is_custom: bool


def _effective(agent_val: Optional[int], global_default: int) -> tuple[int, bool]:
    """Return (effective_value, is_custom_override)."""
    if agent_val is not None:
        return agent_val, True
    return global_default, False


async def get_capacity_for_user(user: User, db: AsyncSession | None = None) -> CapacityOut:
    """Compute effective capacity for any User instance.

    After startup back-fill all capacity columns are non-NULL, so this is
    normally a straight read from the user row.  The db param allows live
    global-settings reads for callers that have a session available.
    """
    from app.routers.settings import SETTINGS_DEFAULTS

    # Prefer live DB settings when a session is available; fall back to the
    # hardcoded schema defaults (guaranteed non-None after startup back-fill).
    if db is not None:
        from app.models import GlobalSettings
        _keys = [
            "default_omni_max", "default_channel_max_voice", "default_channel_max_chat",
            "default_channel_max_whatsapp", "default_channel_max_email", "default_channel_max_sms",
        ]
        rows = (await db.execute(
            select(GlobalSettings).where(GlobalSettings.key.in_(_keys))
        )).scalars().all()
        _live = {r.key: int(r.value) for r in rows}
    else:
        _live = {}

    def _g(key: str, fallback: int) -> int:
        return _live.get(key, int(SETTINGS_DEFAULTS.get(key, fallback)))

    omni,  omni_c  = _effective(user.omni_max,            _g("default_omni_max", 8))
    voice, voice_c = _effective(user.channel_max_voice,   _g("default_channel_max_voice", 1))
    chat,  chat_c  = _effective(user.channel_max_chat,    _g("default_channel_max_chat", 5))
    wa,    wa_c    = _effective(user.channel_max_whatsapp, _g("default_channel_max_whatsapp", 3))
    email, email_c = _effective(user.channel_max_email,   _g("default_channel_max_email", 5))
    sms,   sms_c   = _effective(user.channel_max_sms,     _g("default_channel_max_sms", 5))

    return CapacityOut(
        omni_max=omni,               omni_max_is_custom=omni_c,
        channel_max_voice=voice,     channel_max_voice_is_custom=voice_c,
        channel_max_chat=chat,       channel_max_chat_is_custom=chat_c,
        channel_max_whatsapp=wa,     channel_max_whatsapp_is_custom=wa_c,
        channel_max_email=email,     channel_max_email_is_custom=email_c,
        channel_max_sms=sms,         channel_max_sms_is_custom=sms_c,
        capacity_override_active=bool(user.capacity_override_active),
    )


# ── Lookup: channel string → capacity field name ─────────────────────────────
CHANNEL_CAP_FIELD = {
    "voice":     "channel_max_voice",
    "chat":      "channel_max_chat",
    "whatsapp":  "channel_max_whatsapp",
    "email":     "channel_max_email",
    "sms":       "channel_max_sms",
}

CHANNEL_DEFAULT_KEY = {
    "voice":     "default_channel_max_voice",
    "chat":      "default_channel_max_chat",
    "whatsapp":  "default_channel_max_whatsapp",
    "email":     "default_channel_max_email",
    "sms":       "default_channel_max_sms",
}


@router.get("/me/capacity", response_model=CapacityOut)
async def get_my_capacity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the effective capacity limits for the authenticated agent."""
    return await get_capacity_for_user(current_user, db=db)


@router.post("/me/pick-next", status_code=204)
async def pick_next(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activate a one-shot +1 capacity override.

    The agent can claim one interaction above their omni limit.
    The flag clears automatically after the next interaction is claimed
    (enforced in the WS ``take`` handler and the availability sweep).
    """
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.capacity_override_active:
        # Already armed — idempotent, do nothing
        return
    user.capacity_override_active = True
    await db.commit()


class LimitsIn(BaseModel):
    """Per-agent capacity override request. Pass None to reset a field to the global default."""
    omni_max:             Optional[int] = None
    channel_max_voice:    Optional[int] = None
    channel_max_chat:     Optional[int] = None
    channel_max_whatsapp: Optional[int] = None
    channel_max_email:    Optional[int] = None
    channel_max_sms:      Optional[int] = None


@router.patch("/me/limits", response_model=CapacityOut)
async def update_my_limits(
    body: LimitsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save personal capacity overrides. Pass None for a field to revert to the global default."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    def _clamp(v: Optional[int], lo: int, hi: int) -> Optional[int]:
        if v is None:
            return None
        return max(lo, min(hi, v))

    user.omni_max             = _clamp(body.omni_max,             1, 50)
    user.channel_max_voice    = _clamp(body.channel_max_voice,    1, 10)
    user.channel_max_chat     = _clamp(body.channel_max_chat,     1, 20)
    user.channel_max_whatsapp = _clamp(body.channel_max_whatsapp, 1, 20)
    user.channel_max_email    = _clamp(body.channel_max_email,    1, 20)
    user.channel_max_sms      = _clamp(body.channel_max_sms,      1, 20)
    await db.commit()
    await db.refresh(user)
    return await get_capacity_for_user(user)


# ── Admin: manage capacity for any user ──────────────────────────────────────

def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only admin / super_admin may update another user's capacity limits."""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


@router.get("/{user_id}/capacity", response_model=CapacityOut)
async def get_agent_capacity(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    """Return the effective capacity limits for any agent. Admin only."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await get_capacity_for_user(user)


@router.patch("/{user_id}/limits", response_model=CapacityOut)
async def update_agent_limits(
    user_id: str,
    body: LimitsIn,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    """Set per-agent capacity overrides for any user. Admin only. Pass None to reset to global default."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    def _clamp(v: Optional[int], lo: int, hi: int) -> Optional[int]:
        if v is None:
            return None
        return max(lo, min(hi, v))

    user.omni_max             = _clamp(body.omni_max,             1, 50)
    user.channel_max_voice    = _clamp(body.channel_max_voice,    1, 10)
    user.channel_max_chat     = _clamp(body.channel_max_chat,     1, 20)
    user.channel_max_whatsapp = _clamp(body.channel_max_whatsapp, 1, 20)
    user.channel_max_email    = _clamp(body.channel_max_email,    1, 20)
    user.channel_max_sms      = _clamp(body.channel_max_sms,      1, 20)
    await db.commit()
    await db.refresh(user)
    return await get_capacity_for_user(user)
