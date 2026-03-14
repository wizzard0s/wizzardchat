"""Campaign outbound dialler endpoints — preview and progressive modes.

Supports:
  - Voice / SMS / Email campaigns     : no window constraints
  - WhatsApp outbound campaigns        : enforces the 24-hour free-messaging
    window rule.  If the contact's last *inbound* WhatsApp conversation is
    older than 24 h (or there is no inbound history), ``template_required``
    is set to True and the campaign's ``message_template`` (HSM) is returned
    so the agent sends the approved template instead of free-form text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    AttemptStatus,
    Campaign,
    CampaignAttempt,
    CampaignStatus,
    CampaignType,
    ChannelType,
    Contact,
    ContactListMember,
    Conversation,
    MessageTemplate,
    User,
    VoiceConnector,
    campaign_contact_lists,
)
from app.schemas import (
    CampaignAttemptCreate,
    CampaignAttemptOut,
    CampaignAttemptUpdate,
    ContactDiallerOut,
    ContactHistoryItem,
    DiallerNextOut,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/campaigns",
    tags=["dialler"],
    dependencies=[Depends(get_current_user)],
)

_WA_WINDOW_HOURS = 24  # WhatsApp free-messaging window duration
_TERMINAL_STATUSES = (AttemptStatus.COMPLETED, AttemptStatus.SKIPPED)

# Channel type strings used in outbound_config
_CHANNEL_VOICE    = "voice"
_CHANNEL_WHATSAPP = "whatsapp"
_CHANNEL_SMS      = "sms"
_CHANNEL_EMAIL    = "email"

_CAMPAIGN_TYPE_TO_CHANNEL: dict[CampaignType, str] = {
    CampaignType.OUTBOUND_VOICE:     _CHANNEL_VOICE,
    CampaignType.OUTBOUND_WHATSAPP:  _CHANNEL_WHATSAPP,
    CampaignType.OUTBOUND_SMS:       _CHANNEL_SMS,
    CampaignType.OUTBOUND_EMAIL:     _CHANNEL_EMAIL,
}


# ─────────────────────────── helpers ────────────────────────────────────────

def _is_wa_campaign(campaign: Campaign) -> bool:
    return campaign.campaign_type == CampaignType.OUTBOUND_WHATSAPP


def _active_channel(campaign: Campaign) -> str:
    """Determine the active outbound channel for this campaign.

    Prefers outbound_config.primary_channel when set; falls back to the
    campaign_type mapping.
    """
    cfg = campaign.outbound_config or {}
    primary = cfg.get("primary_channel")
    if primary in (_CHANNEL_VOICE, _CHANNEL_WHATSAPP, _CHANNEL_SMS, _CHANNEL_EMAIL):
        return primary
    return _CAMPAIGN_TYPE_TO_CHANNEL.get(campaign.campaign_type, _CHANNEL_VOICE)


async def _load_template_for_channel(
    channel: str,
    outbound_config: dict,
    db: AsyncSession,
) -> Optional[object]:
    """Return a template-like object for the given channel.

    For SMS/Email: loads a local ``MessageTemplate`` from the database.
    For WhatsApp:  builds a synthetic object from the Meta template fields
                   stored in ``outbound_config`` (wa_meta_template_name, etc.)
                   so no local WA records are needed.
    """
    if channel == _CHANNEL_WHATSAPP:
        name = outbound_config.get("wa_meta_template_name")
        if not name:
            return None
        from types import SimpleNamespace
        import re as _re
        body = outbound_config.get("wa_meta_template_body", "")
        var_positions = sorted(set(int(x) for x in _re.findall(r"\{\{(\d+)\}\}", body)))
        variables = [
            {"pos": p, "label": f"Variable {p}", "contact_field": None, "default": ""}
            for p in var_positions
        ]
        return SimpleNamespace(
            id=None,
            name=name,
            channel=_CHANNEL_WHATSAPP,
            body=body,
            subject=None,
            wa_template_name=name,
            wa_language=outbound_config.get("wa_meta_template_lang", "en"),
            wa_approval_status="APPROVED",
            variables=variables,
        )

    key = f"{channel}_template_id"
    tid = outbound_config.get(key)
    if not tid:
        return None
    try:
        from uuid import UUID as _UUID
        uid = _UUID(str(tid))
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(MessageTemplate).where(MessageTemplate.id == uid)
    )
    return result.scalar_one_or_none()


def _resolve_template_variables(
    template: MessageTemplate,
    contact: Optional[Contact],
) -> list:
    """Return [{pos, label, contact_field, resolved_value}, ...] for the template."""
    out = []
    for v in (template.variables or []):
        pos = v.get("pos", 0)
        label = v.get("label", f"Variable {pos}")
        field = v.get("contact_field")
        default = v.get("default", "")
        value = default
        if contact and field:
            value = str(getattr(contact, field, "") or default)
        out.append({"pos": pos, "label": label, "contact_field": field, "resolved_value": value})
    return out


async def _wa_window_open(contact_id: UUID, db: AsyncSession) -> bool:
    """Return True if there is a WhatsApp inbound conversation from this contact
    within the last 24 hours — meaning free-form messaging is still allowed."""
    cutoff = datetime.utcnow() - timedelta(hours=_WA_WINDOW_HOURS)
    result = await db.execute(
        select(Conversation.id)
        .where(
            and_(
                Conversation.contact_id == contact_id,
                Conversation.channel == ChannelType.WHATSAPP,
                Conversation.direction == "inbound",
                Conversation.created_at >= cutoff,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _campaign_contacts_subquery(campaign_id: UUID):
    """Subquery: distinct contact_ids belonging to this campaign's contact lists."""
    return (
        select(ContactListMember.contact_id.distinct().label("contact_id"))
        .join(
            campaign_contact_lists,
            ContactListMember.contact_list_id == campaign_contact_lists.c.contact_list_id,
        )
        .where(campaign_contact_lists.c.campaign_id == campaign_id)
        .subquery()
    )


async def _get_campaign_or_404(campaign_id: UUID, db: AsyncSession) -> Campaign:
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _progress_counts(campaign_id: UUID, db: AsyncSession) -> tuple[int, int, int]:
    """Return (total_contacts, attempted_contacts, completed_contacts)."""
    members_sq = _campaign_contacts_subquery(campaign_id)

    total_r = await db.execute(
        select(func.count()).select_from(members_sq)
    )
    total = total_r.scalar() or 0

    attempted_r = await db.execute(
        select(func.count(CampaignAttempt.contact_id.distinct())).where(
            CampaignAttempt.campaign_id == campaign_id
        )
    )
    attempted = attempted_r.scalar() or 0

    completed_r = await db.execute(
        select(func.count(CampaignAttempt.contact_id.distinct())).where(
            and_(
                CampaignAttempt.campaign_id == campaign_id,
                CampaignAttempt.status == AttemptStatus.COMPLETED,
            )
        )
    )
    completed = completed_r.scalar() or 0

    return total, attempted, completed


async def _next_contact(campaign: Campaign, db: AsyncSession) -> Optional[Contact]:
    """Return the next dialable contact, respecting max_attempts, retry_interval,
    opt-out flags (CPA / ECTA) and deduplication.

    Priority order:
      1. Contacts never attempted in this campaign.
      2. Contacts whose last attempt is outside the retry window and who
         have not yet hit max_attempts, and have no terminal attempt.

    Contacts with ``do_not_call=True`` (voice) or ``do_not_whatsapp=True``
    (WhatsApp campaigns) are permanently skipped.
    """
    cid = campaign.id
    members_sq = _campaign_contacts_subquery(cid)

    # Contacts already in a terminal state for this campaign
    terminal_sq = (
        select(CampaignAttempt.contact_id.distinct().label("contact_id"))
        .where(
            and_(
                CampaignAttempt.campaign_id == cid,
                CampaignAttempt.status.in_(list(_TERMINAL_STATUSES)),
            )
        )
        .subquery()
    )

    # Per-contact stats: attempt count and last attempted_at
    stats_sq = (
        select(
            CampaignAttempt.contact_id.label("contact_id"),
            func.count(CampaignAttempt.id).label("attempt_count"),
            func.max(CampaignAttempt.created_at).label("last_at"),
        )
        .where(CampaignAttempt.campaign_id == cid)
        .group_by(CampaignAttempt.contact_id)
        .subquery()
    )

    retry_cutoff = datetime.utcnow() - timedelta(seconds=campaign.retry_interval or 3600)

    # CPA / ECTA: determine which opt-out column to filter on
    is_voice = campaign.campaign_type == CampaignType.OUTBOUND_VOICE
    is_wa    = campaign.campaign_type == CampaignType.OUTBOUND_WHATSAPP
    is_sms   = campaign.campaign_type == CampaignType.OUTBOUND_SMS

    q = (
        select(Contact)
        .join(members_sq, Contact.id == members_sq.c.contact_id)
        .outerjoin(terminal_sq, Contact.id == terminal_sq.c.contact_id)
        .outerjoin(stats_sq, Contact.id == stats_sq.c.contact_id)
        .where(
            # Not already in a terminal state
            terminal_sq.c.contact_id == None,  # noqa: E711
            # Either never attempted OR within retry rules
            or_(
                stats_sq.c.contact_id == None,  # never attempted — noqa: E711
                and_(
                    stats_sq.c.attempt_count < (campaign.max_attempts or 3),
                    stats_sq.c.last_at < retry_cutoff,
                ),
            ),
        )
        .order_by(stats_sq.c.last_at.asc().nullsfirst())
        .limit(1)
    )

    # CPA / ECTA: filter opt-out contacts
    if is_voice:
        q = q.where(Contact.do_not_call.is_(False))
    elif is_wa:
        q = q.where(Contact.do_not_whatsapp.is_(False))
    elif is_sms:
        q = q.where(Contact.do_not_sms.is_(False))

    result = await db.execute(q)
    return result.scalar_one_or_none()


async def _contact_attempt_history(contact_id: UUID, campaign_id: UUID, db: AsyncSession) -> list:
    """Return previous attempt records for this contact in this campaign."""
    result = await db.execute(
        select(CampaignAttempt)
        .where(
            and_(
                CampaignAttempt.contact_id == contact_id,
                CampaignAttempt.campaign_id == campaign_id,
            )
        )
        .order_by(CampaignAttempt.created_at.desc())
        .limit(10)
    )
    return result.scalars().all()


# ─────────────────────────── endpoints ──────────────────────────────────────

@router.get("/{campaign_id}/dialler/next", response_model=DiallerNextOut)
async def dialler_next(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return the next contact to dial, WA window state, and campaign progress.

    For voice campaigns this also checks the CPA / ECTA calling-hours window.
    A 400 is returned if the current SAST time is outside the legal window.
    """
    campaign = await _get_campaign_or_404(campaign_id, db)
    if campaign.status != CampaignStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Campaign is '{campaign.status}' — must be 'running' to use dialler",
        )

    # CPA / ECTA: enforce calling hours for voice campaigns before doing any DB work
    if campaign.campaign_type == CampaignType.OUTBOUND_VOICE:
        from app.voice_utils import CallingHoursError, assert_calling_hours
        calling_hours = (campaign.settings or {}).get("calling_hours")
        try:
            assert_calling_hours(calling_hours)
        except CallingHoursError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    total, attempted, completed = await _progress_counts(campaign_id, db)
    contact = await _next_contact(campaign, db)

    outbound_cfg = campaign.outbound_config or {}
    channel = _active_channel(campaign)

    if not contact:
        return DiallerNextOut(
            contact=None,
            attempt=None,
            template_required=False,
            message_template=None,
            active_channel=channel,
            template_id=None,
            template_variables=[],
            outbound_config=outbound_cfg,
            total_contacts=total,
            attempted_contacts=attempted,
            completed_contacts=completed,
            remaining_contacts=max(0, total - completed),
            campaign_exhausted=True,
        )

    wa_open: Optional[bool] = None
    template_required = False
    if _is_wa_campaign(campaign):
        wa_open = await _wa_window_open(contact.id, db)
        template_required = not wa_open

    # Load and resolve template for the active channel
    tmpl = await _load_template_for_channel(channel, outbound_cfg, db)
    resolved_vars: list = []
    tmpl_id: Optional[str] = None
    if tmpl:
        tmpl_id = str(tmpl.id)
        resolved_vars = _resolve_template_variables(tmpl, contact)
        # For WA campaigns: template is always required when window is closed;
        # for other channels the template is informational (agent copies/sends it)
        if not _is_wa_campaign(campaign):
            template_required = True

    return DiallerNextOut(
        contact=ContactDiallerOut.model_validate(contact),
        attempt=None,
        template_required=template_required,
        message_template=campaign.message_template if template_required else None,
        active_channel=channel,
        template_id=tmpl_id,
        template_variables=resolved_vars,
        outbound_config=outbound_cfg,
        total_contacts=total,
        attempted_contacts=attempted,
        completed_contacts=completed,
        remaining_contacts=max(0, total - completed),
        campaign_exhausted=False,
    )


@router.post(
    "/{campaign_id}/dialler/attempt",
    response_model=CampaignAttemptOut,
    status_code=201,
)
async def begin_attempt(
    campaign_id: UUID,
    body: CampaignAttemptCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Record that an agent has started dialling a contact.

    For progressive voice campaigns this also places the outbound call
    automatically via the configured VoiceConnector provider.
    """
    campaign = await _get_campaign_or_404(campaign_id, db)

    # Count existing attempts to set attempt_number
    cnt_r = await db.execute(
        select(func.count(CampaignAttempt.id)).where(
            and_(
                CampaignAttempt.campaign_id == campaign_id,
                CampaignAttempt.contact_id == body.contact_id,
            )
        )
    )
    attempt_number = (cnt_r.scalar() or 0) + 1

    wa_open: Optional[bool] = None
    if _is_wa_campaign(campaign):
        wa_open = await _wa_window_open(body.contact_id, db)

    attempt = CampaignAttempt(
        campaign_id=campaign_id,
        contact_id=body.contact_id,
        agent_id=body.agent_id or user.id,
        attempt_number=attempt_number,
        status=AttemptStatus.DIALLING,
        wa_window_open=wa_open,
        dialled_at=datetime.utcnow(),
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)

    # ── Progressive voice: place the call automatically ────────────────────
    settings = campaign.settings or {}
    dialler_mode  = settings.get("dialler_mode", "preview")
    connector_id  = settings.get("voice_connector_id")

    if (
        campaign.campaign_type == CampaignType.OUTBOUND_VOICE
        and dialler_mode == "progressive"
        and connector_id
    ):
        from app.voice_utils import CallingHoursError, assert_calling_hours, place_outbound_call

        # Enforce calling hours a second time at the point of dialling
        try:
            assert_calling_hours(settings.get("calling_hours"))
        except CallingHoursError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        conn_result = await db.execute(
            select(VoiceConnector).where(VoiceConnector.id == connector_id)
        )
        connector = conn_result.scalar_one_or_none()

        contact_result = await db.execute(
            select(Contact).where(Contact.id == body.contact_id)
        )
        contact = contact_result.scalar_one_or_none()

        if connector and connector.is_active and contact and contact.phone:
            base = str(request.base_url).rstrip("/")
            did_list = connector.did_numbers or []
            from_num = campaign.caller_id or (did_list[0] if did_list else "")
            try:
                call_ref = await place_outbound_call(
                    provider=connector.provider,
                    connector=connector,
                    to_number=contact.phone,
                    from_number=from_num,
                    twiml_url=f"{base}/api/v1/voice/twiml/outbound/{attempt.id}",
                    status_callback_url=f"{base}/api/v1/voice/status/{attempt.id}",
                    base_url=base,
                    attempt_id=str(attempt.id),
                )
                attempt.notes = f"{connector.provider}_ref:{call_ref}"
                await db.flush()
                _log.info(
                    "Progressive call placed: attempt=%s provider=%s ref=%s",
                    attempt.id, connector.provider, call_ref,
                )
            except Exception as exc:
                _log.error("Failed to place progressive call: %s", exc)
                attempt.notes = f"call_error:{exc}"
                await db.flush()

    return CampaignAttemptOut.model_validate(attempt)


@router.patch(
    "/{campaign_id}/dialler/attempt/{attempt_id}",
    response_model=CampaignAttemptOut,
)
async def update_attempt(
    campaign_id: UUID,
    attempt_id: UUID,
    body: CampaignAttemptUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Wrap-up: log outcome, update status, and optionally record timing."""
    result = await db.execute(
        select(CampaignAttempt).where(
            and_(
                CampaignAttempt.id == attempt_id,
                CampaignAttempt.campaign_id == campaign_id,
            )
        )
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(attempt, field, value)

    # Auto-stamp ended_at if transitioning to a terminal state and not already set
    terminal_transition = body.status in _TERMINAL_STATUSES or body.status in (
        AttemptStatus.NO_ANSWER,
        AttemptStatus.BUSY,
        AttemptStatus.FAILED,
    )
    if terminal_transition and not attempt.ended_at:
        attempt.ended_at = datetime.utcnow()

    # Compute handle_duration if we now have both connected_at and ended_at
    if attempt.connected_at and attempt.ended_at and not attempt.handle_duration:
        delta = attempt.ended_at - attempt.connected_at
        attempt.handle_duration = max(0, int(delta.total_seconds()))

    await db.flush()
    await db.refresh(attempt)
    return CampaignAttemptOut.model_validate(attempt)


@router.get("/{campaign_id}/dialler/progress")
async def dialler_progress(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lightweight progress poll used by the dialler header bar."""
    campaign = await _get_campaign_or_404(campaign_id, db)
    total, attempted, completed = await _progress_counts(campaign_id, db)

    # Breakdown by terminal status
    status_counts: dict[str, int] = {}
    for s in (
        AttemptStatus.COMPLETED,
        AttemptStatus.NO_ANSWER,
        AttemptStatus.BUSY,
        AttemptStatus.FAILED,
        AttemptStatus.SKIPPED,
    ):
        r = await db.execute(
            select(func.count(CampaignAttempt.id)).where(
                and_(
                    CampaignAttempt.campaign_id == campaign_id,
                    CampaignAttempt.status == s,
                )
            )
        )
        status_counts[s.value] = r.scalar() or 0

    return {
        "campaign_id": str(campaign_id),
        "campaign_name": campaign.name,
        "campaign_status": campaign.status.value,
        "dialler_mode": (campaign.settings or {}).get("dialler_mode", "preview"),
        "total": total,
        "attempted": attempted,
        "completed": completed,
        "remaining": max(0, total - completed),
        "pct_complete": round(completed / total * 100, 1) if total else 0,
        "by_status": status_counts,
    }


@router.get("/{campaign_id}/dialler/history/{contact_id}")
async def contact_history(
    campaign_id: UUID,
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return prior attempts for a contact within this campaign."""
    attempts = await _contact_attempt_history(contact_id, campaign_id, db)
    return [CampaignAttemptOut.model_validate(a) for a in attempts]


@router.get("/contact/{contact_id}/history")
async def contact_cross_campaign_history(
    contact_id: UUID,
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return the last N days of campaign attempts across ALL campaigns for a contact.

    Returns a list of ContactHistoryItem objects, newest first.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(CampaignAttempt, Campaign)
        .join(Campaign, CampaignAttempt.campaign_id == Campaign.id)
        .where(
            and_(
                CampaignAttempt.contact_id == contact_id,
                CampaignAttempt.created_at >= cutoff,
            )
        )
        .order_by(CampaignAttempt.created_at.desc())
        .limit(100)
    )

    rows = result.all()

    items = []
    for attempt, campaign in rows:
        # Map campaign_type to a channel string
        channel = _CAMPAIGN_TYPE_TO_CHANNEL.get(campaign.campaign_type, "voice")
        items.append(
            ContactHistoryItem(
                id=attempt.id,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                channel=channel,
                direction="outbound",
                status=attempt.status.value if attempt.status else "unknown",
                outcome_code=attempt.outcome_code,
                notes=attempt.notes,
                dialled_at=attempt.dialled_at,
                ended_at=attempt.ended_at,
                handle_duration=attempt.handle_duration,
                created_at=attempt.created_at,
            )
        )

    return items
