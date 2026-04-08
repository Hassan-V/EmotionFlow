import uuid
import os
import aiofiles
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
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {ext}. Allowed: {settings.ALLOWED_EXTENSIONS}",
        )

    # Read file with size check
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # Check user quota
    if user.quota_used_today >= user.quota_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily quota exceeded ({user.quota_limit} analyses/day)",
        )

    # Test account restrictions: fast tier only, max 5 jobs/day
    if user.is_test_account:
        if model_tier != "fast":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Test accounts are limited to the 'fast' tier",
            )
        TEST_ACCOUNT_DAILY_LIMIT = 5
        if user.quota_used_today >= TEST_ACCOUNT_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Test account daily limit reached ({TEST_ACCOUNT_DAILY_LIMIT} analyses/day)",
            )

    # Save file
    job_id = str(uuid.uuid4())
    safe_filename = f"{job_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Capture which API key (if any) authenticated this request
    api_key_id = getattr(request.state, "api_key_id", None)

    # Create job record
    job = AnalysisJob(
        job_id=job_id,
        user_id=user.id,
        api_key_id=api_key_id,
        filename=file.filename or "unknown",
        file_path=file_path,
        file_size_bytes=len(content),
        audio_format=ext.lstrip("."),
        model_tier=model_tier,
        status="pending",
    )
    db.add(job)

    # Increment quota
    user.quota_used_today += 1
    await db.commit()

    # Enqueue for worker processing (pass api_key_id so worker can write billing record)
    await enqueue_analysis_job(
        job_id, safe_filename, model_tier,
        user_id=user.id, session_id=session_id, api_key_id=api_key_id,
    )

    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=f"Analysis queued with '{model_tier}' tier. Poll GET /analysis/jobs/{job_id} for status.",
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
