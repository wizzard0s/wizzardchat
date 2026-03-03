"""Chat connector CRUD – create, manage and embed chat widgets."""

import secrets
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Bump this whenever the visitor chat-widget.js changes protocol/API
# so browsers discard their cached copy.
_WIDGET_VERSION = "5"  # SSE + HTTP POST (no WebSocket) + restart + end-chat button

from app.database import get_db
from app.models import Connector, Flow
from app.schemas import ConnectorCreate, ConnectorUpdate, ConnectorOut
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/connectors",
    tags=["connectors"],
    dependencies=[Depends(get_current_user)],
)

_DEFAULT_STYLE = {
    "theme": "light",
    "primary_color": "#0d6efd",
    "bg_color": "#ffffff",
    "text_color": "#212529",
    "title": "Chat with us",
    "subtitle": "We typically reply within minutes",
    "logo_url": "",
    "position": "bottom-right",
    "launcher_icon": "bi-chat-dots-fill",
    "width": "380px",
    "height": "520px",
    "border_radius": "12px",
}


def _generate_api_key() -> str:
    return secrets.token_urlsafe(32)


# ──────────── Endpoints ────────────────────────────────────────────

@router.get("", response_model=List[ConnectorOut])
async def list_connectors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).order_by(Connector.created_at.desc()))
    return [ConnectorOut.model_validate(c) for c in result.scalars().all()]


@router.post("", response_model=ConnectorOut, status_code=201)
async def create_connector(body: ConnectorCreate, db: AsyncSession = Depends(get_db)):
    style = {**_DEFAULT_STYLE, **body.style}
    connector = Connector(
        name=body.name,
        description=body.description,
        api_key=_generate_api_key(),
        flow_id=body.flow_id,
        allowed_origins=body.allowed_origins,
        style=style,
        meta_fields=body.meta_fields,
        is_active=body.is_active,
    )
    db.add(connector)
    await db.flush()
    await db.refresh(connector)
    return ConnectorOut.model_validate(connector)


@router.get("/{connector_id}", response_model=ConnectorOut)
async def get_connector(connector_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    return ConnectorOut.model_validate(c)


@router.put("/{connector_id}", response_model=ConnectorOut)
async def update_connector(connector_id: UUID, body: ConnectorUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "style" and value:
            # Merge style rather than replace
            current_style = c.style or {}
            setattr(c, "style", {**current_style, **value})
        else:
            setattr(c, field, value)
    await db.flush()
    await db.refresh(c)
    return ConnectorOut.model_validate(c)


@router.post("/{connector_id}/regenerate-key", response_model=ConnectorOut)
async def regenerate_api_key(connector_id: UUID, db: AsyncSession = Depends(get_db)):
    """Issue a fresh API key for the connector (invalidates the old one)."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    c.api_key = _generate_api_key()
    await db.flush()
    await db.refresh(c)
    return ConnectorOut.model_validate(c)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(connector_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    await db.delete(c)


@router.get("/{connector_id}/snippet")
async def get_snippet(connector_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the HTML embed snippet for this connector."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    base_url = str(request.base_url).rstrip("/")
    snippet = f"""<!-- WizzardChat Widget — {c.name} -->
<script>
(function(){{
  window.WizzardChat = {{
    apiKey: '{c.api_key}',
    serverUrl: '{base_url}'
  }};
  var s = document.createElement('script');
  s.async = true;
  s.src = window.WizzardChat.serverUrl + '/static/js/chat-widget.js?v={_WIDGET_VERSION}';
  document.head.appendChild(s);
}})();
</script>"""
    return {"snippet": snippet, "api_key": c.api_key, "server_url": base_url}
