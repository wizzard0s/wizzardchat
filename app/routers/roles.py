"""Custom role management endpoints."""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CustomRole
from app.schemas import RoleCreate, RoleUpdate, RoleOut, ALL_PERMISSIONS
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/roles",
    tags=["roles"],
    dependencies=[Depends(get_current_user)],
)

# ── Default permissions for each seeded system role ──────────────────────────

_ALL = {p: True for p in ALL_PERMISSIONS}

SYSTEM_ROLE_DEFAULTS = {
    "super_admin": {
        "description": "Full unrestricted access to everything.",
        "permissions": _ALL,
    },
    "admin": {
        "description": "Administrative access excluding system-level settings.",
        "permissions": {p: True for p in ALL_PERMISSIONS if p != "system.settings"},
    },
    "supervisor": {
        "description": "Manages agents and queues, views reports.",
        "permissions": {
            "dashboard.view": True,
            "flows.view": True,
            "queues.view": True, "queues.create": True, "queues.edit": True,
            "campaigns.view": True,
            "contacts.view": True, "contacts.create": True, "contacts.edit": True, "contacts.delete": True,
            "contact_lists.view": True, "contact_lists.create": True, "contact_lists.edit": True, "contact_lists.delete": True, "contact_lists.import": True,
            "tags.view": True, "tags.create": True, "tags.edit": True, "tags.delete": True,
            "office_hours.view": True, "office_hours.create": True, "office_hours.edit": True, "office_hours.delete": True,
            "connectors.view": True,
            "teams.view": True, "teams.create": True, "teams.edit": True, "teams.delete": True,
            "users.view": True,
            "outcomes.view": True, "outcomes.create": True, "outcomes.edit": True,
            "roles.view": True,
            "reports.view": True,
            "agent_panel.access": True,
        },
    },
    "agent": {
        "description": "Handles customer interactions via the agent panel.",
        "permissions": {
            "dashboard.view": True,
            # Contacts: agents can view, create and edit contacts, but cannot manage lists
            "contacts.view": True,
            "contacts.create": True,
            "contacts.edit": True,
            # Contact lists: agents can view lists and add contacts to existing lists
            "contact_lists.view": True,
            # Tags: agents can view and apply tags, but not manage (create/delete) them
            "tags.view": True,
            # Office Hours: agents can view schedules
            "office_hours.view": True,
            "outcomes.view": True,
            "agent_panel.access": True,
        },
    },
    "viewer": {
        "description": "Read-only access to most areas.",
        "permissions": {p: True for p in ALL_PERMISSIONS if p.endswith(".view") or p == "reports.view"},
    },
}


async def seed_system_roles(db: AsyncSession):
    """Ensure all system roles exist and their permissions are up-to-date (idempotent)."""
    for name, meta in SYSTEM_ROLE_DEFAULTS.items():
        existing = (
            await db.execute(select(CustomRole).where(CustomRole.name == name))
        ).scalar_one_or_none()
        if not existing:
            db.add(CustomRole(
                name=name,
                description=meta["description"],
                is_system=True,
                permissions=meta["permissions"],
            ))
        else:
            # Always refresh system role permissions so new keys take effect on restart
            existing.permissions = meta["permissions"]
    await db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CustomRole).order_by(CustomRole.is_system.desc(), CustomRole.name))
    return [RoleOut.model_validate(r) for r in result.scalars().all()]


@router.get("/permissions")
async def list_permissions():
    """Return all known permission keys grouped by resource."""
    groups: dict = {}
    for p in ALL_PERMISSIONS:
        resource, action = p.rsplit(".", 1)
        groups.setdefault(resource, []).append(action)
    return {"permissions": ALL_PERMISSIONS, "groups": groups}


@router.post("", response_model=RoleOut, status_code=201)
async def create_role(body: RoleCreate, db: AsyncSession = Depends(get_db)):
    if body.name in SYSTEM_ROLE_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"'{body.name}' is a reserved system role name.")
    existing = (await db.execute(select(CustomRole).where(CustomRole.name == body.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A role with that name already exists.")
    role = CustomRole(
        name=body.name,
        description=body.description,
        is_system=False,
        permissions=body.permissions,
    )
    db.add(role)
    await db.flush()
    await db.refresh(role)
    await db.commit()
    return RoleOut.model_validate(role)


@router.get("/{role_id}", response_model=RoleOut)
async def get_role(role_id: UUID, db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(CustomRole).where(CustomRole.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return RoleOut.model_validate(role)


@router.put("/{role_id}", response_model=RoleOut)
async def update_role(role_id: UUID, body: RoleUpdate, db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(CustomRole).where(CustomRole.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be modified.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.flush()
    await db.refresh(role)
    await db.commit()
    return RoleOut.model_validate(role)


@router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: UUID, db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(CustomRole).where(CustomRole.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be deleted.")
    await db.delete(role)
    await db.commit()
