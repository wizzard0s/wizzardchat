"""WizzardAI integration proxy.

Keeps WizzardAI credentials server-side. The browser never sees the API key.
All LLM calls from the UI go through these endpoints.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import get_settings
from app.models import User

log = logging.getLogger("wizzardchat.ai")

router = APIRouter(
    prefix="/api/v1/ai",
    tags=["ai"],
    dependencies=[Depends(get_current_user)],
)


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    system_prompt: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.4
    max_tokens: int = 2048
    variables: dict[str, Any] = {}


# ── Health / status ──────────────────────────────────────────────────────────

@router.get("/status")
async def ai_status():
    """Check whether WizzardAI is reachable at the configured URL."""
    settings = get_settings()
    base = settings.wizzardai_base_url.rstrip("/")
    if not base:
        return {"ok": False, "reason": "WIZZARDAI_BASE_URL is not configured"}
    headers = {"X-WizzardAI-Key": settings.wizzardai_api_key} if settings.wizzardai_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{base}/api/inference/health", headers=headers)
            data = r.json() if r.status_code == 200 else {}
            return {"ok": r.status_code == 200, "providers_online": data.get("providers_online", []), "base_url": base}
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "base_url": base}


# ── Chat proxy ───────────────────────────────────────────────────────────────

@router.post("/chat")
async def ai_chat(body: ChatRequest):
    """
    Proxy a chat message to WizzardAI /api/inference.
    Keeps the API key server-side.
    Returns {ok, response, model, provider, tokens_used}.
    """
    settings = get_settings()
    base = settings.wizzardai_base_url.rstrip("/")
    if not base:
        raise HTTPException(503, "WizzardAI is not configured. Set WIZZARDAI_BASE_URL in .env")

    headers = {
        "Content-Type": "application/json",
        **({"X-WizzardAI-Key": settings.wizzardai_api_key} if settings.wizzardai_api_key else {}),
    }

    payload = {
        "model":       body.model,
        "system_prompt": body.system_prompt,
        "messages":    [{"role": m.role, "content": m.content} for m in body.messages],
        "temperature": body.temperature,
        "max_tokens":  body.max_tokens,
        "variables":   body.variables,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{base}/api/inference", json=payload, headers=headers)

        if r.status_code == 401:
            raise HTTPException(503, "WizzardAI rejected the API key — check WIZZARDAI_API_KEY in .env")
        if r.status_code != 200:
            raise HTTPException(502, f"WizzardAI returned HTTP {r.status_code}: {r.text[:200]}")

        return r.json()

    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot reach WizzardAI at {base}. Is it running?")
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("AI chat proxy failed")
        raise HTTPException(500, str(exc))
