"""Survey reporting endpoints — CSAT and NPS.

Survey data is written directly by the flow engine when a flow's `end` node fires
and the flow context contains well-known variables (csat_score, nps_score, etc.).
No custom API call is needed inside the sub-flow.

GET  /api/v1/reporting/csat
GET  /api/v1/reporting/nps
    Aggregated survey results for the dashboard.  Both require agent auth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Interaction, User

router = APIRouter(prefix="/api/v1", tags=["csat"])


# ── CSAT reporting ────────────────────────────────────────────────────────────

@router.get(
    "/reporting/csat",
    summary="Aggregated CSAT report (requires auth)",
)
async def get_csat_report(
    queue_id:    Optional[str] = None,
    date_from:   Optional[str] = None,   # YYYY-MM-DD
    date_to:     Optional[str] = None,   # YYYY-MM-DD
    db:          AsyncSession  = Depends(get_db),
    _current:    User          = Depends(get_current_user),
):
    from sqlalchemy import and_, cast, Integer

    q = select(
        func.count(Interaction.csat_score).label("total_responses"),
        func.round(func.avg(cast(Interaction.csat_score, Integer)), 2).label("average_score"),
        func.count(Interaction.id).filter(Interaction.csat_score == 1).label("score_1"),
        func.count(Interaction.id).filter(Interaction.csat_score == 2).label("score_2"),
        func.count(Interaction.id).filter(Interaction.csat_score == 3).label("score_3"),
        func.count(Interaction.id).filter(Interaction.csat_score == 4).label("score_4"),
        func.count(Interaction.id).filter(Interaction.csat_score == 5).label("score_5"),
    ).where(Interaction.csat_score.isnot(None))

    filters = []
    if queue_id:
        try:
            filters.append(Interaction.queue_id == UUID(queue_id))
        except ValueError:
            pass
    if date_from:
        try:
            filters.append(Interaction.csat_submitted_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            filters.append(Interaction.csat_submitted_at <= datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError:
            pass
    if filters:
        q = q.where(and_(*filters))

    row = (await db.execute(q)).one()

    total = row.total_responses or 0
    promoters   = row.score_5 or 0            # score 5
    detractors  = (row.score_1 or 0) + (row.score_2 or 0)   # scores 1-2
    csat_pct    = round((promoters / total * 100) if total else 0, 1)

    # Recent comments (last 50 with a comment)
    comments_q = (
        select(
            Interaction.id,
            Interaction.csat_score,
            Interaction.csat_comment,
            Interaction.csat_submitted_at,
        )
        .where(Interaction.csat_comment.isnot(None))
        .order_by(Interaction.csat_submitted_at.desc())
        .limit(50)
    )
    if filters:
        comments_q = comments_q.where(and_(*filters))
    comments_rows = (await db.execute(comments_q)).fetchall()

    return {
        "summary": {
            "total_responses":  total,
            "average_score":    float(row.average_score or 0),
            "csat_percent":     csat_pct,          # % of score-5 responses
            "distribution": {
                "1": row.score_1,
                "2": row.score_2,
                "3": row.score_3,
                "4": row.score_4,
                "5": row.score_5,
            },
        },
        "recent_comments": [
            {
                "interaction_id": str(r.id),
                "score": r.csat_score,
                "comment": r.csat_comment,
                "submitted_at": r.csat_submitted_at.isoformat() if r.csat_submitted_at else None,
            }
            for r in comments_rows
        ],
    }


# ── NPS reporting ─────────────────────────────────────────────────────────────

@router.get(
    "/reporting/nps",
    summary="Aggregated NPS report (requires auth)",
)
async def get_nps_report(
    queue_id:    Optional[str] = None,
    date_from:   Optional[str] = None,   # YYYY-MM-DD
    date_to:     Optional[str] = None,   # YYYY-MM-DD
    db:          AsyncSession  = Depends(get_db),
    _current:    User          = Depends(get_current_user),
):
    from sqlalchemy import and_, cast, Integer

    q = select(
        func.count(Interaction.nps_score).label("total_responses"),
        func.round(func.avg(cast(Interaction.nps_score, Integer)), 2).label("average_score"),
        # Promoters = 9-10, Passives = 7-8, Detractors = 0-6
        func.count(Interaction.id).filter(Interaction.nps_score >= 9).label("promoters"),
        func.count(Interaction.id).filter(
            Interaction.nps_score >= 7, Interaction.nps_score <= 8
        ).label("passives"),
        func.count(Interaction.id).filter(Interaction.nps_score <= 6).label("detractors"),
    ).where(Interaction.nps_score.isnot(None))

    filters = []
    if queue_id:
        try:
            filters.append(Interaction.queue_id == UUID(queue_id))
        except ValueError:
            pass
    if date_from:
        try:
            filters.append(Interaction.nps_submitted_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            filters.append(Interaction.nps_submitted_at <= datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError:
            pass
    if filters:
        q = q.where(and_(*filters))

    row = (await db.execute(q)).one()

    total      = row.total_responses or 0
    promoters  = row.promoters  or 0
    detractors = row.detractors or 0
    nps_score  = round(((promoters - detractors) / total * 100) if total else 0, 1)

    # Recent reasons (last 50 with a reason)
    reasons_q = (
        select(
            Interaction.id,
            Interaction.nps_score,
            Interaction.nps_reason,
            Interaction.nps_submitted_at,
        )
        .where(Interaction.nps_reason.isnot(None))
        .order_by(Interaction.nps_submitted_at.desc())
        .limit(50)
    )
    if filters:
        reasons_q = reasons_q.where(and_(*filters))
    reason_rows = (await db.execute(reasons_q)).fetchall()

    return {
        "summary": {
            "total_responses": total,
            "average_score":   float(row.average_score or 0),
            "nps_score":       nps_score,   # true NPS: % promoters - % detractors
            "promoters":       promoters,
            "passives":        row.passives or 0,
            "detractors":      detractors,
        },
        "recent_reasons": [
            {
                "interaction_id": str(r.id),
                "score":         r.nps_score,
                "reason":        r.nps_reason,
                "submitted_at":  r.nps_submitted_at.isoformat() if r.nps_submitted_at else None,
            }
            for r in reason_rows
        ],
    }
