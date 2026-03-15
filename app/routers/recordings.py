"""Call Recordings router.

Endpoints
---------
POST /api/v1/voice/recording/twilio/{attempt_id}
    Twilio ``recordingStatusCallback`` — fires when Twilio finishes processing
    a recording.  Accepted for every leg (outbound contact leg, conference leg).

POST /api/v1/voice/recording/vonage/{attempt_id}
    Vonage ``recordingEventUrl`` — fires with recording metadata when Vonage
    finishes a conversation recording.

GET  /api/v1/recordings
    List recordings (supervisor / manager view).  Filterable by campaign,
    agent, contact, date range, leg, status.  Requires authenticated user.

GET  /api/v1/recordings/{recording_id}
    Single recording detail.

GET  /api/v1/recordings/{recording_id}/audio
    Stream / serve the audio file.  Supports ``Range`` header for seekable
    HTML5 <audio> playback.  Falls back to a presigned S3 redirect or
    provider_url redirect when the local file is not available.

DELETE /api/v1/recordings/{recording_id}
    Soft-delete (marks status=FAILED, removes file).  Supervisor only.

Storage backends
----------------
Controlled by ``RECORDING_STORAGE`` in .env:

  local (default)
      Files written to  <project_root>/wizzrecordings/<year>/<mm>/<dd>/<id>.<ext>

  s3
      Files uploaded to S3-compatible storage (AWS S3 or Wasabi).
      Set RECORDING_S3_BUCKET, RECORDING_S3_ACCESS_KEY, RECORDING_S3_SECRET_KEY.
      For Wasabi set RECORDING_S3_ENDPOINT_URL (e.g. https://s3.wasabisys.com).
      Playback URLs are short-lived presigned GET URLs (RECORDING_S3_PRESIGN_TTL).
      Set RECORDING_LOCAL_CACHE=true (default) to also keep a local copy for
      fast seek without hitting the presign quota.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db, async_session
from app.models import (
    CampaignAttempt, CallRecording, Campaign, UserRole,
    RecordingLeg, RecordingStatus,
)
from app.schemas import CallRecordingOut

_log  = logging.getLogger(__name__)
_cfg  = get_settings()

router = APIRouter(prefix="/api/v1", tags=["recordings"])

# Local storage root:  <WIZZARDCHAT>/wizzrecordings/
_BASE_DIR      = Path(__file__).resolve().parents[2]
RECORDINGS_DIR = _BASE_DIR / "wizzrecordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


# ─── S3 / Wasabi client (lazy singleton) ──────────────────────────────────────

_s3_client = None


def _get_s3():
    """Return a boto3 S3 client, creating it once.  Returns None if not configured."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    if _cfg.recording_storage != "s3" or not _cfg.recording_s3_bucket:
        return None
    try:
        import boto3  # noqa: PLC0415
        kwargs: dict = {
            "aws_access_key_id":     _cfg.recording_s3_access_key or None,
            "aws_secret_access_key": _cfg.recording_s3_secret_key or None,
            "region_name":           _cfg.recording_s3_region or "us-east-1",
        }
        if _cfg.recording_s3_endpoint_url:
            kwargs["endpoint_url"] = _cfg.recording_s3_endpoint_url
        _s3_client = boto3.client("s3", **kwargs)
        return _s3_client
    except ImportError:
        _log.warning("boto3 not installed — S3/Wasabi storage unavailable. pip install boto3")
        return None


def _s3_key(recording_id: uuid.UUID, dt: datetime | None, ext: str) -> str:
    """Build S3 object key: <prefix>/<year>/<mm>/<dd>/<recording_id>.<ext>"""
    now    = dt or datetime.utcnow()
    prefix = (_cfg.recording_s3_prefix or "wizzrecordings").rstrip("/")
    return f"{prefix}/{now.year}/{now.month:02d}/{now.day:02d}/{recording_id}.{ext}"


def _s3_presign(key: str) -> str | None:
    """Generate a presigned GET URL for the given S3 key.  Returns None on error."""
    s3 = _get_s3()
    if not s3:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": _cfg.recording_s3_bucket, "Key": key},
            ExpiresIn=_cfg.recording_s3_presign_ttl,
        )
    except Exception as _e:
        _log.error("S3 presign failed for key=%s: %s", key, _e)
        return None


async def _upload_to_s3(data: bytes, key: str, mime: str) -> bool:
    """Upload bytes to S3/Wasabi in a thread pool executor.  Returns True on success."""
    s3 = _get_s3()
    if not s3:
        return False
    try:
        import asyncio as _aio  # noqa: PLC0415
        loop = _aio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: s3.put_object(
                Bucket=_cfg.recording_s3_bucket,
                Key=key,
                Body=data,
                ContentType=mime,
                ServerSideEncryption="AES256",
            ),
        )
        _log.info("S3 upload OK: s3://%s/%s (%d bytes)", _cfg.recording_s3_bucket, key, len(data))
        return True
    except Exception as _e:
        _log.error("S3 upload failed key=%s: %s", key, _e)
        return False


# ─── Internal helpers ──────────────────────────────────────────────────────────

async def _create_recording_row(
    *,
    db: AsyncSession,
    attempt_id: uuid.UUID,
    provider: str,
    leg: str,
    provider_recording_id: str | None,
    provider_url: str | None,
    duration_seconds: int | None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> CallRecording:
    """Insert (or return existing) a CallRecording row for this attempt+provider_recording_id."""
    # Idempotency: if we already have a row for this provider recording ID, return it
    if provider_recording_id:
        existing = (await db.execute(
            select(CallRecording).where(
                CallRecording.provider_recording_id == provider_recording_id
            )
        )).scalar_one_or_none()
        if existing:
            return existing

    # Fetch attempt context for denormalisation
    att_row = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    attempt = att_row.scalar_one_or_none()

    rec = CallRecording(
        attempt_id=attempt_id,
        campaign_id=attempt.campaign_id if attempt else None,
        agent_id=attempt.agent_id if attempt else None,
        contact_id=attempt.contact_id if attempt else None,
        provider=provider,
        leg=leg,
        status=RecordingStatus.PENDING.value,
        provider_recording_id=provider_recording_id,
        provider_url=provider_url,
        duration_seconds=duration_seconds,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


def _local_path(recording_id: uuid.UUID, dt: datetime | None, ext: str = "mp3") -> Path:
    """Build local path: wizzrecordings/<year>/<mm>/<dd>/<recording_id>.<ext>"""
    now    = dt or datetime.utcnow()
    folder = RECORDINGS_DIR / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{recording_id}.{ext}"


async def _schedule_download(
    recording_id: uuid.UUID,
    provider_url: str,
    provider: str,
    auth: tuple[str, str] | None,
) -> None:
    """Schedule a background coroutine to download the recording file."""
    asyncio.create_task(_download_recording(recording_id, provider_url, provider, auth))


async def _download_recording(
    recording_id: uuid.UUID,
    provider_url: str,
    provider: str,
    auth: tuple[str, str] | None,
) -> None:
    """Download the provider recording file and persist to configured storage backend(s).

    Storage behaviour:
      local  → write to  wizzrecordings/<year>/<mm>/<dd>/<id>.<ext>
      s3     → upload to S3/Wasabi; also write local cache if RECORDING_LOCAL_CACHE=true
    """
    async with async_session() as db:
        rec_row = (await db.execute(
            select(CallRecording).where(CallRecording.id == recording_id)
        )).scalar_one_or_none()
        if not rec_row:
            _log.warning("_download_recording: recording %s not found", recording_id)
            return

        rec_row.status = RecordingStatus.DOWNLOADING.value
        await db.commit()

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                kwargs: dict = {"url": provider_url, "follow_redirects": True}
                if auth:
                    kwargs["auth"] = auth
                response = await client.get(**kwargs)
                response.raise_for_status()

            ct  = response.headers.get("content-type", "audio/mpeg")
            ext = "mp3"
            if "wav" in ct:
                ext = "wav"
            elif "ogg" in ct:
                ext = "ogg"
            elif "mp4" in ct or "m4a" in ct:
                ext = "m4a"

            raw_data = response.content
            mime     = ct.split(";")[0].strip()

            # Determine storage paths / keys
            use_s3    = _cfg.recording_storage == "s3" and bool(_cfg.recording_s3_bucket)
            use_local = (not use_s3) or _cfg.recording_local_cache

            s3_key_val: str | None = None
            local_rel:  str | None = None

            # ── S3 / Wasabi upload ────────────────────────────────────────────
            if use_s3:
                s3_key_val = _s3_key(recording_id, rec_row.created_at, ext)
                ok = await _upload_to_s3(raw_data, s3_key_val, mime)
                if not ok:
                    _log.warning("S3 upload failed; falling back to local for recording %s", recording_id)
                    use_local = True  # always save locally if S3 fails

            # ── Local write ───────────────────────────────────────────────────
            if use_local:
                dest = _local_path(recording_id, rec_row.created_at, ext)
                dest.write_bytes(raw_data)
                local_rel = str(dest.relative_to(_BASE_DIR))

            # ── Update DB row ─────────────────────────────────────────────────
            async with async_session() as db2:
                rec2 = (await db2.execute(
                    select(CallRecording).where(CallRecording.id == recording_id)
                )).scalar_one_or_none()
                if rec2:
                    rec2.mime_type       = mime
                    rec2.file_size_bytes = len(raw_data)
                    rec2.status          = RecordingStatus.AVAILABLE.value

                    # file_path stores the local relative path when cached locally,
                    # or the S3 key (prefixed "s3:") when S3-only
                    if local_rel:
                        rec2.file_path = local_rel
                    elif s3_key_val:
                        rec2.file_path = f"s3:{s3_key_val}"

                    # Promote to attempt.recording_url for merged/outbound legs
                    if rec2.leg in (RecordingLeg.MERGED.value, RecordingLeg.OUTBOUND.value):
                        att = (await db2.execute(
                            select(CampaignAttempt).where(CampaignAttempt.id == rec2.attempt_id)
                        )).scalar_one_or_none()
                        if att and not att.recording_url:
                            att.recording_url = f"/api/v1/recordings/{recording_id}/audio"
                    await db2.commit()
                    _log.info(
                        "Recording %s stored — local=%s s3_key=%s (%d bytes)",
                        recording_id, local_rel, s3_key_val, len(raw_data),
                    )

        except Exception as exc:
            _log.error("_download_recording %s failed: %s", recording_id, exc)
            async with async_session() as db3:
                rec3 = (await db3.execute(
                    select(CallRecording).where(CallRecording.id == recording_id)
                )).scalar_one_or_none()
                if rec3:
                    rec3.status        = RecordingStatus.FAILED.value
                    rec3.error_message = str(exc)
                    await db3.commit()


def _build_out(rec: CallRecording) -> CallRecordingOut:
    """Build CallRecordingOut, resolving playback_url for local or S3 storage."""
    d  = rec.__dict__.copy()
    fp = rec.file_path or ""

    if fp.startswith("s3:"):
        # S3-only — return a presigned URL directly so the browser can play the file
        s3_key    = fp[3:]
        presigned = _s3_presign(s3_key)
        d["playback_url"] = presigned or f"/api/v1/recordings/{rec.id}/audio"
    elif fp and rec.status == RecordingStatus.AVAILABLE.value and (_BASE_DIR / fp).exists():
        d["playback_url"] = f"/api/v1/recordings/{rec.id}/audio"
    elif rec.provider_url:
        # Proxy through our endpoint so we can add provider auth headers
        d["playback_url"] = f"/api/v1/recordings/{rec.id}/audio"
    else:
        d["playback_url"] = None

    return CallRecordingOut.model_validate(d)


# ─── Provider webhooks (no auth — URLs contain opaque attempt UUID) ─────────


@router.post("/voice/recording/twilio/{attempt_id}", include_in_schema=False)
async def twilio_recording_callback(
    attempt_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    RecordingSid: str = Form(None),
    RecordingUrl: str = Form(None),
    RecordingDuration: str = Form(None),
    RecordingStatus_: str = Form(None, alias="RecordingStatus"),
    RecordingSource: str = Form(None),  # DialConferenceLeg | RecordVerb | ...
):
    """Twilio fires this when a recording is ready (status=completed)."""
    status_val = (RecordingStatus_ or "").lower()
    if status_val not in ("completed", ""):
        # in-progress or failed — ignore or log
        _log.info("twilio recording %s status=%s — skipping", RecordingSid, status_val)
        return {"ok": True}

    if not RecordingUrl:
        _log.warning("twilio_recording_callback: no RecordingUrl for attempt=%s", attempt_id)
        return {"ok": True}

    # Twilio recording URL needs .mp3 appended unless already present
    dl_url = RecordingUrl if RecordingUrl.endswith((".mp3", ".wav")) else RecordingUrl + ".mp3"

    # Map RecordingSource to leg type
    source_to_leg: dict[str, str] = {
        "DialConferenceLeg": RecordingLeg.OUTBOUND.value,
        "RecordVerb":        RecordingLeg.MERGED.value,
        "DialVerb":          RecordingLeg.OUTBOUND.value,
        "OutboundAPI":       RecordingLeg.OUTBOUND.value,
    }
    leg = source_to_leg.get(RecordingSource or "", RecordingLeg.MERGED.value)

    duration = int(RecordingDuration) if RecordingDuration and RecordingDuration.isdigit() else None

    # Fetch auth_token for Twilio download auth
    att_row = await db.execute(
        select(CampaignAttempt).where(CampaignAttempt.id == attempt_id)
    )
    att = att_row.scalar_one_or_none()
    auth: tuple[str, str] | None = None
    if att:
        camp_row = await db.execute(
            select(Campaign).where(Campaign.id == att.campaign_id)
        )
        camp = camp_row.scalar_one_or_none()
        from app.models import VoiceConnector  # noqa: PLC0415
        conn_id = (camp.settings or {}).get("voice_connector_id") if camp else None
        if conn_id:
            try:
                vc_row = await db.execute(
                    select(VoiceConnector).where(
                        VoiceConnector.id == uuid.UUID(str(conn_id))
                    )
                )
                vc = vc_row.scalar_one_or_none()
                if vc and vc.account_sid and vc.auth_token:
                    auth = (vc.account_sid, vc.auth_token)
            except Exception as _e:
                _log.warning("twilio_recording_callback: connector lookup: %s", _e)

    rec = await _create_recording_row(
        db=db,
        attempt_id=attempt_id,
        provider="twilio",
        leg=leg,
        provider_recording_id=RecordingSid,
        provider_url=dl_url,
        duration_seconds=duration,
    )
    background_tasks.add_task(_download_recording, rec.id, dl_url, "twilio", auth)
    return {"ok": True}


@router.post("/voice/recording/vonage/{attempt_id}", include_in_schema=False)
async def vonage_recording_callback(
    attempt_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Vonage fires this (recordingEventUrl) when a conversation recording is ready."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    rec_url  = body.get("recording_url") or body.get("url")
    rec_id   = str(body.get("recording_uuid") or body.get("id") or "")
    duration = body.get("duration")
    duration_s = int(duration) if duration else None

    if not rec_url:
        _log.warning("vonage_recording_callback: no url for attempt=%s body=%s", attempt_id, body)
        return {"ok": True}

    rec = await _create_recording_row(
        db=db,
        attempt_id=attempt_id,
        provider="vonage",
        leg=RecordingLeg.MERGED.value,
        provider_recording_id=rec_id or None,
        provider_url=rec_url,
        duration_seconds=duration_s,
    )
    # Vonage recording URLs require a JWT bearer token — pass None for now;
    # authenticated download can be added when Vonage JWT generation is wired.
    background_tasks.add_task(_download_recording, rec.id, rec_url, "vonage", None)
    return {"ok": True}


# ─── Authenticated recording API ──────────────────────────────────────────────


@router.get("/recordings", summary="List call recordings (supervisor)")
async def list_recordings(
    campaign_id:  Optional[uuid.UUID] = Query(None),
    agent_id:     Optional[uuid.UUID] = Query(None),
    contact_id:   Optional[uuid.UUID] = Query(None),
    attempt_id:   Optional[uuid.UUID] = Query(None),
    leg:          Optional[str]       = Query(None, description="outbound|agent|merged|ivr|hold|barge|transfer"),
    status:       Optional[str]       = Query(None, description="pending|downloading|available|failed|provider"),
    date_from:    Optional[str]       = Query(None, description="YYYY-MM-DD"),
    date_to:      Optional[str]       = Query(None, description="YYYY-MM-DD"),
    page:         int                 = Query(1, ge=1),
    page_size:    int                 = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    q = select(CallRecording).order_by(CallRecording.created_at.desc())
    if campaign_id:  q = q.where(CallRecording.campaign_id == campaign_id)
    if agent_id:     q = q.where(CallRecording.agent_id    == agent_id)
    if contact_id:   q = q.where(CallRecording.contact_id  == contact_id)
    if attempt_id:   q = q.where(CallRecording.attempt_id  == attempt_id)
    if leg:          q = q.where(CallRecording.leg    == leg)
    if status:       q = q.where(CallRecording.status == status)
    if date_from:
        try:
            q = q.where(CallRecording.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.where(CallRecording.created_at < datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError:
            pass

    offset = (page - 1) * page_size
    rows = (await db.execute(q.offset(offset).limit(page_size))).scalars().all()
    return [_build_out(r) for r in rows]


@router.get("/recordings/{recording_id}", summary="Get single recording")
async def get_recording(
    recording_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rec = (await db.execute(
        select(CallRecording).where(CallRecording.id == recording_id)
    )).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return _build_out(rec)


@router.get("/recordings/{recording_id}/audio", summary="Stream recording audio")
async def stream_recording(
    recording_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    request: Request = None,
):
    """Serve the audio for playback in the browser.

    Resolution order:
      1. Local file (wizzrecordings/…) — streamed with Range support
      2. S3/Wasabi (file_path starts with "s3:") — 302 to a presigned URL
      3. provider_url — 302 to provider (Twilio/Vonage CDN)
      4. 404
    """
    rec = (await db.execute(
        select(CallRecording).where(CallRecording.id == recording_id)
    )).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    fp = rec.file_path or ""

    # ── Local file ────────────────────────────────────────────────────────────
    if fp and not fp.startswith("s3:"):
        full_path = _BASE_DIR / fp
        if full_path.exists():
            return FileResponse(
                path=str(full_path),
                media_type=rec.mime_type or "audio/mpeg",
                headers={"Accept-Ranges": "bytes"},
            )

    # ── S3 / Wasabi ───────────────────────────────────────────────────────────
    if fp.startswith("s3:"):
        presigned = _s3_presign(fp[3:])
        if presigned:
            return RedirectResponse(url=presigned, status_code=302)
        # S3 presigning failed — fall through to provider_url

    # ── Provider CDN URL ──────────────────────────────────────────────────────
    if rec.provider_url:
        return RedirectResponse(url=rec.provider_url, status_code=302)

    raise HTTPException(status_code=404, detail="Audio file not yet available")


@router.delete("/recordings/{recording_id}", summary="Delete recording (supervisor)")
async def delete_recording(
    recording_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    # Only supervisors and above may delete recordings
    allowed = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.SUPERVISOR}
    if current_user.role not in allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    rec = (await db.execute(
        select(CallRecording).where(CallRecording.id == recording_id)
    )).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Remove local file
    if rec.file_path:
        try:
            _file = _BASE_DIR / rec.file_path
            if _file.exists():
                _file.unlink()
        except OSError as _e:
            _log.warning("delete_recording: file removal failed: %s", _e)

    rec.file_path        = None
    rec.status           = RecordingStatus.FAILED.value
    rec.error_message    = f"Deleted by {current_user.username} at {datetime.utcnow().isoformat()}"
    await db.commit()
    return {"ok": True}
