"""Contact & Contact List management  full CRUD + CSV upload."""

import csv
import io
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Contact, ContactList, ContactListMember
from app.schemas import (
    ContactCreate, ContactUpdate, ContactOut, ContactListRef,
    ContactListCreate, ContactListUpdate, ContactListOut,
)
from app.auth import get_current_user, require_permission

router = APIRouter(
    prefix="/api/v1/contacts",
    tags=["contacts"],
    dependencies=[Depends(get_current_user)],
)

#  CSV column  model field map 
CSV_FIELD_MAP = {
    "first_name": "first_name", "firstname": "first_name", "first": "first_name",
    "last_name": "last_name",  "lastname": "last_name",  "last": "last_name",
    "title": "title", "salutation": "title",
    "job_title": "job_title", "jobtitle": "job_title", "position": "job_title",
    "company": "company", "organisation": "company", "organization": "company",
    "email": "email", "email_address": "email",
    "phone": "phone", "phone_number": "phone", "mobile": "phone", "cell": "phone",
    "whatsapp": "whatsapp_id", "whatsapp_id": "whatsapp_id",
    "address": "address_line1", "address_line1": "address_line1", "street": "address_line1",
    "city": "city", "town": "city",
    "state": "state", "province": "state", "region": "state",
    "postal_code": "postal_code", "postcode": "postal_code", "zip": "postal_code",
    "country": "country",
    "dob": "date_of_birth", "date_of_birth": "date_of_birth", "birthday": "date_of_birth",
    "gender": "gender", "sex": "gender",
    "language": "language",
    "source": "source",
    "tags": "tags",
    "notes": "notes", "note": "notes",
}

CONTACT_FIELDS = {
    "first_name", "last_name", "title", "job_title", "company",
    "email", "phone", "whatsapp_id",
    "address_line1", "city", "state", "postal_code", "country",
    "date_of_birth", "gender", "language", "source", "tags", "notes",
}


#  Helpers 

async def _get_contact_or_404(contact_id: UUID, db: AsyncSession) -> Contact:
    result = await db.execute(
        select(Contact)
        .options(selectinload(Contact.list_memberships).selectinload(ContactListMember.contact_list))
        .where(Contact.id == contact_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    return c


def _build_contact_out(c: Contact) -> dict:
    try:
        data = ContactOut.model_validate(c).model_dump()
    except Exception:
        # Fallback: build manually so one bad contact never breaks the whole list
        data = {
            "id": str(c.id),
            "first_name": c.first_name, "last_name": c.last_name,
            "title": c.title, "job_title": c.job_title, "company": c.company,
            "email": c.email, "phone": c.phone, "whatsapp_id": c.whatsapp_id,
            "address_line1": c.address_line1, "city": c.city, "state": c.state,
            "postal_code": c.postal_code, "country": c.country,
            "date_of_birth": c.date_of_birth, "gender": c.gender, "language": c.language,
            "source": c.source, "status": (c.status.value if c.status else "active"),
            "tags": c.tags or [], "custom_fields": c.custom_fields or {}, "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "lists": [],
        }
    data["lists"] = [
        {"id": str(m.contact_list_id), "name": m.contact_list.name}
        for m in (c.list_memberships or [])
        if m.contact_list is not None
    ]
    return data


async def _cl_with_count(cl: ContactList, db: AsyncSession) -> dict:
    cnt = await db.scalar(
        select(func.count()).where(ContactListMember.contact_list_id == cl.id)
    )
    d = ContactListOut.model_validate(cl).model_dump()
    d["member_count"] = cnt or 0
    return d


# 
# IMPORTANT: all static sub-paths must come BEFORE /{contact_id} so FastAPI
# does not attempt to parse e.g. "lists" or "count" as a UUID and return 422.
# 

#  Contact list routes 

@router.get("/lists/all", response_model=List[ContactListOut])
@router.get("/lists", response_model=List[ContactListOut])
async def list_contact_lists(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission("contact_lists.view")),
):
    result = await db.execute(select(ContactList).order_by(ContactList.name))
    return [await _cl_with_count(cl, db) for cl in result.scalars().all()]


@router.post("/lists", response_model=ContactListOut, status_code=201,
             dependencies=[Depends(require_permission("contact_lists.create"))])
async def create_contact_list(body: ContactListCreate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    cl = ContactList(**data)
    db.add(cl)
    await db.flush()
    await db.refresh(cl)
    return await _cl_with_count(cl, db)


@router.get("/lists/{list_id}", response_model=ContactListOut,
            dependencies=[Depends(require_permission("contact_lists.view"))])
async def get_contact_list(list_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactList).where(ContactList.id == list_id))
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="List not found")
    return await _cl_with_count(cl, db)


@router.put("/lists/{list_id}", response_model=ContactListOut,
            dependencies=[Depends(require_permission("contact_lists.edit"))])
async def update_contact_list(list_id: UUID, body: ContactListUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactList).where(ContactList.id == list_id))
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="List not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cl, k, v)
    await db.flush()
    await db.refresh(cl)
    return await _cl_with_count(cl, db)


@router.delete("/lists/{list_id}", status_code=204,
               dependencies=[Depends(require_permission("contact_lists.delete"))])
async def delete_contact_list(list_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactList).where(ContactList.id == list_id))
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="List not found")
    await db.delete(cl)


@router.get("/lists/{list_id}/members", response_model=List[ContactOut],
            dependencies=[Depends(require_permission("contact_lists.view"))])
async def list_members(
    list_id: UUID,
    search: str = "",
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Contact)
        .options(selectinload(Contact.list_memberships).selectinload(ContactListMember.contact_list))
        .join(ContactListMember, ContactListMember.contact_id == Contact.id)
        .where(ContactListMember.contact_list_id == list_id)
        .order_by(Contact.last_name, Contact.first_name)
        .offset(offset).limit(limit)
    )
    if search:
        p = f"%{search}%"
        q = q.where(Contact.first_name.ilike(p) | Contact.last_name.ilike(p) | Contact.email.ilike(p))
    result = await db.execute(q)
    return [_build_contact_out(c) for c in result.scalars().all()]


@router.post("/lists/{list_id}/members/{contact_id}", status_code=204,
             dependencies=[Depends(require_permission("contacts.create"))])
async def add_to_list(list_id: UUID, contact_id: UUID, db: AsyncSession = Depends(get_db)):
    exists = await db.scalar(
        select(ContactListMember).where(
            ContactListMember.contact_list_id == list_id,
            ContactListMember.contact_id == contact_id,
        )
    )
    if not exists:
        db.add(ContactListMember(contact_list_id=list_id, contact_id=contact_id))


@router.delete("/lists/{list_id}/members/{contact_id}", status_code=204,
               dependencies=[Depends(require_permission("contacts.edit"))])
async def remove_from_list(list_id: UUID, contact_id: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(
        delete(ContactListMember).where(
            ContactListMember.contact_list_id == list_id,
            ContactListMember.contact_id == contact_id,
        )
    )


#  Bulk operations 

@router.post("/bulk/delete", status_code=200,
             dependencies=[Depends(require_permission("contacts.delete"))])
async def bulk_delete(ids: List[UUID], db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Contact).where(Contact.id.in_(ids)))
    return {"deleted": len(ids)}


@router.post("/bulk/add-to-list",
             dependencies=[Depends(require_permission("contacts.create"))])
async def bulk_add_to_list(list_id: UUID, ids: List[UUID], db: AsyncSession = Depends(get_db)):
    inserted = 0
    for cid in ids:
        exists = await db.scalar(
            select(ContactListMember).where(
                ContactListMember.contact_list_id == list_id,
                ContactListMember.contact_id == cid,
            )
        )
        if not exists:
            db.add(ContactListMember(contact_list_id=list_id, contact_id=cid))
            inserted += 1
    return {"added": inserted}


#  CSV Upload 

@router.post("/upload/preview",
             dependencies=[Depends(require_permission("contact_lists.import"))])
async def preview_csv(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    rows = []
    for i, row in enumerate(reader):
        if i >= 5:
            break
        rows.append(dict(row))
    suggestions = {
        h: CSV_FIELD_MAP[h.lower().strip().replace(" ", "_")]
        for h in headers
        if h.lower().strip().replace(" ", "_") in CSV_FIELD_MAP
    }
    return {"headers": headers, "preview_rows": rows, "suggestions": suggestions}


@router.post("/upload/import",
             dependencies=[Depends(require_permission("contact_lists.import"))])
async def import_csv(
    file: UploadFile = File(...),
    list_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    created = skipped = errors = 0
    contact_ids = []

    for row in reader:
        try:
            kwargs: dict = {}
            for csv_col, val in row.items():
                field = CSV_FIELD_MAP.get(csv_col.lower().strip().replace(" ", "_"))
                if field and field in CONTACT_FIELDS and val and val.strip():
                    kwargs[field] = [t.strip() for t in val.split(",") if t.strip()] if field == "tags" else val.strip()
            if not any(kwargs.get(f) for f in ("email", "phone", "first_name")):
                skipped += 1
                continue
            contact = Contact(**kwargs)
            db.add(contact)
            await db.flush()
            contact_ids.append(contact.id)
            created += 1
        except Exception:
            errors += 1

    if list_id and contact_ids:
        lid = UUID(list_id)
        for cid in contact_ids:
            exists = await db.scalar(
                select(ContactListMember).where(
                    ContactListMember.contact_list_id == lid,
                    ContactListMember.contact_id == cid,
                )
            )
            if not exists:
                db.add(ContactListMember(contact_list_id=lid, contact_id=cid))

    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


#  Contact count 

@router.get("/count",
            dependencies=[Depends(require_permission("contacts.view"))])
async def count_contacts(
    search: str = "",
    status: Optional[str] = None,
    list_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(func.count()).select_from(Contact)
    if search:
        p = f"%{search}%"
        q = q.where(Contact.first_name.ilike(p) | Contact.last_name.ilike(p) | Contact.email.ilike(p))
    if status:
        q = q.where(Contact.status == status)
    if list_id:
        q = q.join(ContactListMember, ContactListMember.contact_id == Contact.id) \
              .where(ContactListMember.contact_list_id == list_id)
    return {"total": await db.scalar(q) or 0}


#  Contact CRUD  (dynamic routes last) 

@router.get("", response_model=List[ContactOut],
            dependencies=[Depends(require_permission("contacts.view"))])
async def list_contacts(
    search: str = "",
    status: Optional[str] = None,
    list_id: Optional[UUID] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Contact)
        .options(selectinload(Contact.list_memberships).selectinload(ContactListMember.contact_list))
        .order_by(Contact.created_at.desc())
        .offset(offset).limit(limit)
    )
    if search:
        p = f"%{search}%"
        q = q.where(
            Contact.first_name.ilike(p) | Contact.last_name.ilike(p)
            | Contact.email.ilike(p) | Contact.phone.ilike(p) | Contact.company.ilike(p)
        )
    if status:
        q = q.where(Contact.status == status)
    if list_id:
        q = q.join(ContactListMember, ContactListMember.contact_id == Contact.id) \
              .where(ContactListMember.contact_list_id == list_id)
    result = await db.execute(q)
    return [_build_contact_out(c) for c in result.scalars().all()]


@router.post("", response_model=ContactOut, status_code=201,
             dependencies=[Depends(require_permission("contacts.create"))])
async def create_contact(body: ContactCreate, db: AsyncSession = Depends(get_db)):
    kwargs = {k: v for k, v in body.model_dump().items()
              if k in CONTACT_FIELDS or k in ("tags", "custom_fields", "language")}
    c = Contact(**kwargs)
    db.add(c)
    await db.flush()
    c = await _get_contact_or_404(c.id, db)
    return _build_contact_out(c)


@router.get("/{contact_id}", response_model=ContactOut,
            dependencies=[Depends(require_permission("contacts.view"))])
async def get_contact(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    return _build_contact_out(await _get_contact_or_404(contact_id, db))


@router.put("/{contact_id}", response_model=ContactOut,
            dependencies=[Depends(require_permission("contacts.edit"))])
async def update_contact(contact_id: UUID, body: ContactUpdate, db: AsyncSession = Depends(get_db)):
    c = await _get_contact_or_404(contact_id, db)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    await db.flush()
    c = await _get_contact_or_404(contact_id, db)
    return _build_contact_out(c)


@router.delete("/{contact_id}", status_code=204,
               dependencies=[Depends(require_permission("contacts.delete"))])
async def delete_contact(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.delete(c)
