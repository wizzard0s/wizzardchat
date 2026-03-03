"""Tag management – CRUD + assign/remove tags on interactions, contacts, and users."""

import re
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tag, TagType, Interaction, Contact, User, interaction_tags, contact_tags, user_tags
from app.schemas import TagCreate, TagUpdate, TagOut
from app.auth import get_current_user, require_permission

router = APIRouter(
    prefix="/api/v1/tags",
    tags=["tags"],
    dependencies=[Depends(get_current_user)],
)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[TagOut])
async def list_tags(
    tag_type: Optional[TagType] = Query(None),
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("tags.view")),
):
    q = select(Tag).order_by(Tag.tag_type, Tag.name)
    if tag_type:
        q = q.where(Tag.tag_type == tag_type)
    if active_only:
        q = q.where(Tag.is_active == True)
    return [TagOut.model_validate(t) for t in (await db.execute(q)).scalars().all()]


@router.post("", response_model=TagOut, status_code=201,
             dependencies=[Depends(require_permission("tags.create"))])
async def create_tag(body: TagCreate, db: AsyncSession = Depends(get_db)):
    slug = _slugify(body.name)
    clash = (await db.execute(
        select(Tag).where(Tag.slug == slug, Tag.tag_type == body.tag_type)
    )).scalar_one_or_none()
    if clash:
        raise HTTPException(status_code=409, detail=f"Tag '{body.name}' already exists for type '{body.tag_type.value}'")
    tag = Tag(slug=slug, **body.model_dump())
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    await db.commit()
    return TagOut.model_validate(tag)


@router.get("/{tag_id}", response_model=TagOut,
            dependencies=[Depends(require_permission("tags.view"))])
async def get_tag(tag_id: UUID, db: AsyncSession = Depends(get_db)):
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return TagOut.model_validate(tag)


@router.put("/{tag_id}", response_model=TagOut,
            dependencies=[Depends(require_permission("tags.edit"))])
async def update_tag(tag_id: UUID, body: TagUpdate, db: AsyncSession = Depends(get_db)):
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        new_slug = _slugify(updates["name"])
        clash = (await db.execute(
            select(Tag).where(Tag.slug == new_slug, Tag.tag_type == tag.tag_type, Tag.id != tag_id)
        )).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409, detail=f"Tag '{updates['name']}' already exists for this type")
        updates["slug"] = new_slug
    for k, v in updates.items():
        setattr(tag, k, v)
    await db.flush()
    await db.refresh(tag)
    await db.commit()
    return TagOut.model_validate(tag)


@router.delete("/{tag_id}", status_code=204,
               dependencies=[Depends(require_permission("tags.delete"))])
async def delete_tag(tag_id: UUID, db: AsyncSession = Depends(get_db)):
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag)
    await db.commit()


# ── Assign / Remove on entities ───────────────────────────────────────────────

def _check_type(tag: Tag, expected: TagType):
    if tag.tag_type != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Tag '{tag.name}' is of type '{tag.tag_type.value}', not '{expected.value}'"
        )


# ── Interactions ──────────────────────────────────────────────────────────────

@router.get("/interactions/{interaction_id}", response_model=List[TagOut],
            dependencies=[Depends(require_permission("tags.view"))])
async def get_interaction_tags(interaction_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Interaction).options(selectinload(Interaction.tag_refs)).where(Interaction.id == interaction_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return [TagOut.model_validate(t) for t in entity.tag_refs]


@router.post("/interactions/{interaction_id}/{tag_id}", status_code=204)
async def add_tag_to_interaction(
    interaction_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("tags.view")),
):
    entity = (await db.execute(
        select(Interaction).options(selectinload(Interaction.tag_refs)).where(Interaction.id == interaction_id)
    )).scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Interaction not found")
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    _check_type(tag, TagType.INTERACTION)
    if tag not in entity.tag_refs:
        entity.tag_refs.append(tag)
        await db.commit()


@router.delete("/interactions/{interaction_id}/{tag_id}", status_code=204)
async def remove_tag_from_interaction(
    interaction_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("tags.view")),
):
    await db.execute(
        delete(interaction_tags).where(
            interaction_tags.c.interaction_id == interaction_id,
            interaction_tags.c.tag_id == tag_id,
        )
    )
    await db.commit()


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/contacts/{contact_id}", response_model=List[TagOut],
            dependencies=[Depends(require_permission("tags.view"))])
async def get_contact_tags(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Contact).options(selectinload(Contact.tag_refs)).where(Contact.id == contact_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Contact not found")
    return [TagOut.model_validate(t) for t in entity.tag_refs]


@router.post("/contacts/{contact_id}/{tag_id}", status_code=204)
async def add_tag_to_contact(
    contact_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("contacts.edit")),
):
    entity = (await db.execute(
        select(Contact).options(selectinload(Contact.tag_refs)).where(Contact.id == contact_id)
    )).scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Contact not found")
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    _check_type(tag, TagType.CONTACT)
    if tag not in entity.tag_refs:
        entity.tag_refs.append(tag)
        await db.commit()


@router.delete("/contacts/{contact_id}/{tag_id}", status_code=204)
async def remove_tag_from_contact(
    contact_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("contacts.edit")),
):
    await db.execute(
        delete(contact_tags).where(
            contact_tags.c.contact_id == contact_id,
            contact_tags.c.tag_id == tag_id,
        )
    )
    await db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users/{user_id}", response_model=List[TagOut],
            dependencies=[Depends(require_permission("tags.view"))])
async def get_user_tags(user_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(selectinload(User.tag_refs)).where(User.id == user_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="User not found")
    return [TagOut.model_validate(t) for t in entity.tag_refs]


@router.post("/users/{user_id}/{tag_id}", status_code=204)
async def add_tag_to_user(
    user_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("users.edit")),
):
    entity = (await db.execute(
        select(User).options(selectinload(User.tag_refs)).where(User.id == user_id)
    )).scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="User not found")
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    _check_type(tag, TagType.USER)
    if tag not in entity.tag_refs:
        entity.tag_refs.append(tag)
        await db.commit()


@router.delete("/users/{user_id}/{tag_id}", status_code=204)
async def remove_tag_from_user(
    user_id: UUID, tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("users.edit")),
):
    await db.execute(
        delete(user_tags).where(
            user_tags.c.user_id == user_id,
            user_tags.c.tag_id == tag_id,
        )
    )
    await db.commit()
