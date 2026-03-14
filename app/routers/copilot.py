"""
Agent Copilot — WizzardChat
============================
Provides a KB-backed AI assistant for agents.  The copilot:

1. Queries WizzardAI's knowledge vector store for relevant articles.
2. Builds a grounded context from the top results.
3. Calls WizzardAI /api/inference to generate a concise, cited answer.

Configuration is stored as GlobalSettings key ``copilot_config`` (JSON).

Endpoints
---------
GET  /api/v1/copilot/config           get current config
PUT  /api/v1/copilot/config           save config (admin only)
POST /api/v1/copilot/ask              ask the copilot (any authenticated agent)
GET  /api/v1/copilot/kb-sources       list available KB sources from WizzardAI
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import GlobalSettings, User, UserRole

log = logging.getLogger("wizzardchat.copilot")

router = APIRouter(
    prefix="/api/v1/copilot",
    tags=["copilot"],
    dependencies=[Depends(get_current_user)],
)

_CONFIG_KEY = "copilot_config"

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "source_ids": [],          # empty = all sources
    "model": "auto",
    "max_results": 5,
    "system_prompt": (
        "You are an Agent Copilot for a contact centre. "
        "Use only the provided knowledge base excerpts to answer the agent's question. "
        "Be concise and factual. If the answer is not in the provided context, say so clearly. "
        "Always cite the article title when you use information from it."
    ),
}

# ── Pydantic models ──────────────────────────────────────────────────────────

class CopilotConfig(BaseModel):
    enabled: bool = True
    source_ids: list[str] = []
    model: str = "auto"
    max_results: int = 5
    system_prompt: str = _DEFAULT_CONFIG["system_prompt"]


class CopilotMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class CopilotAskRequest(BaseModel):
    question: str
    history: list[CopilotMessage] = []
    session_context: str = ""   # optional: current chat snippet for grounding


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _load_config(db: AsyncSession) -> dict:
    result = await db.execute(
        select(GlobalSettings).where(GlobalSettings.key == _CONFIG_KEY)
    )
    row = result.scalar_one_or_none()
    if not row:
        return dict(_DEFAULT_CONFIG)
    try:
        return {**_DEFAULT_CONFIG, **json.loads(row.value)}
    except (json.JSONDecodeError, TypeError):
        return dict(_DEFAULT_CONFIG)


async def _wizzardai_get(path: str, params: dict | None = None) -> Any:
    settings = get_settings()
    base = settings.wizzardai_base_url.rstrip("/")
    if not base:
        raise HTTPException(503, "WIZZARDAI_BASE_URL is not configured")
    headers = {"X-WizzardAI-Key": settings.wizzardai_api_key} if settings.wizzardai_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}{path}", params=params, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot reach WizzardAI at {base}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"WizzardAI returned {exc.response.status_code}")


async def _wizzardai_post(path: str, payload: dict) -> Any:
    settings = get_settings()
    base = settings.wizzardai_base_url.rstrip("/")
    if not base:
        raise HTTPException(503, "WIZZARDAI_BASE_URL is not configured")
    headers = {
        "Content-Type": "application/json",
        **({"X-WizzardAI-Key": settings.wizzardai_api_key} if settings.wizzardai_api_key else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{base}{path}", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot reach WizzardAI at {base}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"WizzardAI returned {exc.response.status_code}: {exc.response.text[:200]}")


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_copilot_config(db: AsyncSession = Depends(get_db)):
    """Return current copilot configuration."""
    return await _load_config(db)


@router.put("/config")
async def update_copilot_config(
    body: CopilotConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save copilot configuration. Admin only."""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(403, "Admin privileges required")

    value = json.dumps(body.model_dump())
    result = await db.execute(
        select(GlobalSettings).where(GlobalSettings.key == _CONFIG_KEY)
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = value
        row.updated_by = current_user.id
    else:
        db.add(GlobalSettings(
            key=_CONFIG_KEY,
            value=value,
            description="Agent Copilot configuration",
            updated_by=current_user.id,
        ))
    await db.commit()
    return body.model_dump()


@router.get("/kb-sources")
async def list_kb_sources():
    """Proxy the KB sources list from WizzardAI so the UI can populate checkboxes."""
    data = await _wizzardai_get("/api/knowledge/sources")
    # WizzardAI returns the list directly (or wrapped in .sources)
    sources = data if isinstance(data, list) else data.get("sources", data)
    return {"sources": sources}


@router.post("/ask")
async def copilot_ask(
    body: CopilotAskRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Ask the copilot a question.

    1. Searches configured KB sources in WizzardAI.
    2. Builds grounded context from top results.
    3. Calls WizzardAI /api/inference with the context + question.
    4. Returns {answer, sources, model_used, kb_results}.
    """
    config = await _load_config(db)

    if not config.get("enabled", True):
        raise HTTPException(503, "Agent Copilot is disabled")

    # ── Step 1: KB search ────────────────────────────────────────────────────
    source_ids: list[str] = config.get("source_ids", [])
    max_results: int = config.get("max_results", 5)

    if source_ids:
        # Search each configured source, collect and re-rank by score
        all_results: list[dict] = []
        for sid in source_ids:
            try:
                data = await _wizzardai_get(
                    "/api/knowledge/search",
                    params={"q": body.question, "limit": max_results, "source_id": sid},
                )
                all_results.extend(data.get("results", []))
            except HTTPException:
                pass  # one source unavailable — continue with others
        # Sort by score desc and take top max_results
        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
        kb_results = all_results[:max_results]
    else:
        # All sources
        try:
            data = await _wizzardai_get(
                "/api/knowledge/search",
                params={"q": body.question, "limit": max_results},
            )
            kb_results = data.get("results", [])
        except HTTPException:
            kb_results = []

    # ── Step 2: Build grounded context ──────────────────────────────────────
    if kb_results:
        context_lines: list[str] = []
        for i, r in enumerate(kb_results, 1):
            context_lines.append(
                f"[{i}] {r.get('title', 'Article')}\n"
                f"Source: {r.get('url', '')}\n"
                f"{r.get('excerpt', '')}"
            )
        context = "\n\n".join(context_lines)
    else:
        context = "No relevant knowledge base articles found for this query."

    # ── Step 3: Build prompt messages ────────────────────────────────────────
    system_prompt = config.get("system_prompt", _DEFAULT_CONFIG["system_prompt"])
    if body.session_context:
        system_prompt += (
            f"\n\nCurrent conversation context (for reference only):\n{body.session_context}"
        )

    messages: list[dict] = []
    # Include conversation history (up to last 6 turns to stay within context)
    for msg in (body.history or [])[-6:]:
        messages.append({"role": msg.role, "content": msg.content})

    # Append the current question with KB context injected
    messages.append({
        "role": "user",
        "content": (
            f"Knowledge base context:\n{context}\n\n"
            f"Agent question: {body.question}"
        ),
    })

    # ── Step 4: Call WizzardAI inference ────────────────────────────────────
    model = config.get("model", "auto")
    inference_payload: dict[str, Any] = {
        "system_prompt": system_prompt,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    if model and model != "auto":
        inference_payload["model"] = model

    try:
        inf_result = await _wizzardai_post("/api/inference", inference_payload)
        answer = inf_result.get("response", "").strip()
        model_used = inf_result.get("model", model)
    except HTTPException as exc:
        # Return graceful degraded answer if AI is unavailable
        log.warning("Copilot inference failed: %s", exc.detail)
        if kb_results:
            answer = (
                "AI inference is currently unavailable. "
                "Here are the most relevant knowledge base articles I found:\n\n"
                + "\n".join(f"• {r.get('title')} — {r.get('url')}" for r in kb_results)
            )
        else:
            answer = "AI inference is currently unavailable and no matching KB articles were found."
        model_used = None

    return {
        "answer": answer,
        "model_used": model_used,
        "kb_results": [
            {
                "title":   r.get("title"),
                "url":     r.get("url"),
                "excerpt": r.get("excerpt"),
                "score":   r.get("score"),
                "source_id": r.get("source_id"),
            }
            for r in kb_results
        ],
    }
