"""
WizzardChat  Knowledge Base proxy
====================================
The KB is now owned by WizzardAI (ChromaDB + sentence-transformers).
This router is a thin proxy so flow-designer ``kb_search`` nodes can
call WizzardAI's semantic search without hard-coding the upstream URL.

Endpoint
--------
GET /api/v1/kb/search?q=&limit=5&source_id=   --> proxied to WizzardAI
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])

_WIZZARDAI_BASE = os.getenv("WIZZARDAI_BASE_URL", "http://localhost:8080")


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    source_id: Optional[str] = Query(None),
):
    """Proxy a semantic search request to WizzardAI's knowledge store."""
    params: dict = {"q": q, "limit": limit}
    if source_id:
        params["source_id"] = source_id

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_WIZZARDAI_BASE}/api/knowledge/search",
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc))
    except httpx.RequestError as exc:
        logger.error("KB proxy - cannot reach WizzardAI: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Knowledge base service unavailable - WizzardAI is not running.",
        )
