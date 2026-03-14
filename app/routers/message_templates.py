"""Message template management — WhatsApp HSM, SMS body, and Email body templates."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_permission
from app.database import get_db
from app.models import Contact, MessageTemplate, User
from app.schemas import MessageTemplateCreate, MessageTemplateOut, TemplateVariableMap

router = APIRouter(
    prefix="/api/v1/templates",
    tags=["templates"],
    dependencies=[Depends(get_current_user)],
)

# ─────────────────────────── helpers ────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")


def _resolve_body(body: str, variables: list, contact: Contact | None) -> str:
    """Replace {{N}} placeholders in body using contact fields or defaults."""
    var_map: dict[int, str] = {}
    for v in variables:
        pos = v["pos"] if isinstance(v, dict) else v.pos
        field = v.get("contact_field") if isinstance(v, dict) else v.contact_field
        default = v.get("default", "") if isinstance(v, dict) else (v.default or "")
        value = default
        if contact and field:
            value = str(getattr(contact, field, "") or default)
        var_map[pos] = value

    def _sub(m: re.Match) -> str:
        return var_map.get(int(m.group(1)), m.group(0))

    return _PLACEHOLDER_RE.sub(_sub, body)


def _build_resolved_variables(
    variables: list,
    contact: Contact | None,
) -> list[dict]:
    """Return variables list with resolved_value filled in from contact data."""
    out = []
    for v in variables:
        pos = v["pos"] if isinstance(v, dict) else v.pos
        label = v.get("label", f"Variable {pos}") if isinstance(v, dict) else v.label
        field = v.get("contact_field") if isinstance(v, dict) else v.contact_field
        default = v.get("default", "") if isinstance(v, dict) else (v.default or "")
        value = default
        if contact and field:
            value = str(getattr(contact, field, "") or default)
        out.append({"pos": pos, "label": label, "contact_field": field, "resolved_value": value})
    return out


# ─────────────────────────── CRUD endpoints ──────────────────────────────────

@router.get("", response_model=List[MessageTemplateOut])
async def list_templates(
    channel: Optional[str] = Query(None, description="Filter by channel: whatsapp|sms|email"),
    status: Optional[str] = Query(None, description="Filter by status: active|inactive|draft"),
    db: AsyncSession = Depends(get_db),
):
    q = select(MessageTemplate).order_by(MessageTemplate.name)
    if channel:
        q = q.where(MessageTemplate.channel == channel)
    if status:
        q = q.where(MessageTemplate.status == status)
    result = await db.execute(q)
    return [MessageTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=MessageTemplateOut, status_code=201)
async def create_template(
    body: MessageTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("campaigns.edit")),
):
    if body.channel not in ("whatsapp", "sms", "email"):
        raise HTTPException(status_code=422, detail="channel must be whatsapp, sms, or email")
    if body.channel == "whatsapp":
        raise HTTPException(
            status_code=400,
            detail="WhatsApp templates are managed in Meta Business Manager and synced via the WA connector. Create SMS or Email templates here.",
        )
    t = MessageTemplate(
        name=body.name,
        channel=body.channel,
        status=body.status,
        body=body.body,
        subject=body.subject,
        variables=[v.model_dump() for v in body.variables],
        wa_template_name=body.wa_template_name,
        wa_language=body.wa_language,
        wa_approval_status=body.wa_approval_status,
        wa_category=body.wa_category,
        from_name=body.from_name,
        reply_to=body.reply_to,
        created_by=user.id,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return MessageTemplateOut.model_validate(t)


@router.get("/{template_id}", response_model=MessageTemplateOut)
async def get_template(template_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return MessageTemplateOut.model_validate(t)


@router.put("/{template_id}", response_model=MessageTemplateOut)
async def update_template(
    template_id: UUID,
    body: MessageTemplateCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.channel not in ("whatsapp", "sms", "email"):
        raise HTTPException(status_code=422, detail="channel must be whatsapp, sms, or email")
    t.name = body.name
    t.channel = body.channel
    t.status = body.status
    t.body = body.body
    t.subject = body.subject
    t.variables = [v.model_dump() for v in body.variables]
    t.wa_template_name = body.wa_template_name
    t.wa_language = body.wa_language
    t.wa_approval_status = body.wa_approval_status
    t.wa_category = body.wa_category
    t.from_name = body.from_name
    t.reply_to = body.reply_to
    await db.flush()
    await db.refresh(t)
    return MessageTemplateOut.model_validate(t)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("campaigns.edit")),
):
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(t)


@router.post("/{template_id}/resolve")
async def resolve_template(
    template_id: UUID,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Render a template body with contact data substituted into {{N}} placeholders.

    Request body:
      { "contact_id": "<uuid>", "variable_overrides": {"1": "custom value"} }

    Returns:
      { "body": "<resolved string>", "subject": "<resolved or None>",
        "variables": [{pos, label, contact_field, resolved_value}, ...] }
    """
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    contact: Contact | None = None
    contact_id_raw = body.get("contact_id")
    if contact_id_raw:
        try:
            cid = UUID(str(contact_id_raw))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid contact_id")
        cr = await db.execute(select(Contact).where(Contact.id == cid))
        contact = cr.scalar_one_or_none()

    overrides: dict[str, str] = body.get("variable_overrides") or {}

    # Apply overrides on top of contact data
    variables = list(t.variables or [])
    for v in variables:
        pos_key = str(v["pos"] if isinstance(v, dict) else v.pos)
        if pos_key in overrides:
            if isinstance(v, dict):
                v["default"] = overrides[pos_key]

    resolved_vars = _build_resolved_variables(variables, contact)
    resolved_body = _resolve_body(t.body, variables, contact)
    resolved_subject = _resolve_body(t.subject, variables, contact) if t.subject else None

    return {
        "body": resolved_body,
        "subject": resolved_subject,
        "variables": resolved_vars,
    }
