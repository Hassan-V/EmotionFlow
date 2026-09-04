import uuid
import os
import aiofiles
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.models.analysis import AnalysisJob
from app.models.schemas import (
    JobSubmitResponse, JobStatusResponse, ErrorResponse,
)
from app.services.queue_service import enqueue_analysis_job

router = APIRouter(prefix="/analysis", tags=["Analysis"])
settings = get_settings()

UPLOAD_DIR = settings.UPLOAD_DIR or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")


def reset_daily_quota_if_due(user: User, now: datetime | None = None) -> bool:
    """Reset usage after the stored UTC boundary and schedule the next reset."""
    now = now or datetime.now(timezone.utc)
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_at = user.quota_reset_at
    if reset_at is None:
        user.quota_reset_at = next_midnight
        return False
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    if reset_at <= now:
        user.quota_used_today = 0
        user.quota_reset_at = next_midnight
        return True
    return False


def _validate_audio_filename(filename: str) -> tuple[str, str]:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {ext}. Allowed: {settings.ALLOWED_EXTENSIONS}",
        )
    return ext, f"{uuid.uuid4()}{ext}"


async def _queue_audio(
    *,
    request: Request,
    content: bytes,
    filename: str,
    model_tier: str,
    session_id: str,
    user: User,
    db: AsyncSession,
) -> JobSubmitResponse:
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Audio payload is empty")
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )
    ext, safe_filename = _validate_audio_filename(filename)
    locked = (await db.execute(
        select(User).where(User.id == user.id).with_for_update()
    )).scalar_one()
    reset_daily_quota_if_due(locked)
    if locked.quota_used_today >= locked.quota_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily quota exceeded ({locked.quota_limit} analyses/day)",
        )
    if locked.is_test_account:
        if model_tier != "fast":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Test accounts are limited to the 'fast' tier",
            )
        if locked.quota_used_today >= 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Test account daily limit reached (5 analyses/day)",
            )
    job_id = safe_filename.removesuffix(ext)
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    async with aiofiles.open(file_path, "wb") as output:
        await output.write(content)
    api_key_id = getattr(request.state, "api_key_id", None)
    db.add(AnalysisJob(
        job_id=job_id,
        user_id=locked.id,
        api_key_id=api_key_id,
        filename=filename,
        file_path=file_path,
        file_size_bytes=len(content),
        audio_format=ext.lstrip("."),
        model_tier=model_tier,
        status="pending",
    ))
    locked.quota_used_today += 1
    await db.commit()
    await enqueue_analysis_job(
        job_id, safe_filename, model_tier,
        user_id=locked.id, session_id=session_id, api_key_id=api_key_id,
    )
    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=f"Analysis queued with '{model_tier}' tier. Poll GET /analysis/jobs/{job_id} for status.",
    )


@router.post(
    "/analyze-file",
    response_model=JobSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
async def submit_analysis(
    request: Request,
    file: UploadFile = File(...),
    model_tier: str = Query(default="balanced", pattern="^(fast|balanced|max)$"),
    session_id: str = Query(default="", max_length=100, description="Optional session ID for context persistence"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    return await _queue_audio(
        request=request,
        content=content,
        filename=file.filename or "upload.wav",
        model_tier=model_tier,
        session_id=session_id,
        user=user,
        db=db,
    )


@router.post(
    "/analyze-stream",
    response_model=JobSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
async def submit_stream_analysis(
    request: Request,
    filename: str = Query(default="stream.wav", min_length=5, max_length=255),
    model_tier: str = Query(default="fast", pattern="^(fast|balanced|max)$"),
    session_id: str = Query(default="", max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept an HTTP chunked audio body and enqueue one JSON-report job."""
    _validate_audio_filename(filename)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Stream too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB",
            )
    return await _queue_audio(
        request=request,
        content=bytes(content),
        filename=filename,
        model_tier=model_tier,
        session_id=session_id,
        user=user,
        db=db,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisJob).where(
            AnalysisJob.job_id == job_id,
            AnalysisJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.get(
    "/jobs/{job_id}/audio",
    responses={404: {"model": ErrorResponse}},
)
async def get_job_audio(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the original uploaded audio file for a completed job."""
    result = await db.execute(
        select(AnalysisJob).where(
            AnalysisJob.job_id == job_id,
            AnalysisJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.file_path or not os.path.isfile(job.file_path):
        raise HTTPException(status_code=404, detail="Audio file no longer available")

    media_types = {
        "wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac",
        "ogg": "audio/ogg", "m4a": "audio/mp4", "webm": "audio/webm",
    }
    ext = job.audio_format.lower()
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=job.file_path,
        media_type=media_type,
        filename=job.filename,
    )


@router.get("/jobs", response_model=list[JobStatusResponse])
async def list_jobs(
    status_filter: str = Query(default=None, pattern="^(pending|processing|completed|failed)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AnalysisJob).where(AnalysisJob.user_id == user.id)
    if status_filter:
        query = query.where(AnalysisJob.status == status_filter)
    query = query.order_by(AnalysisJob.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()
