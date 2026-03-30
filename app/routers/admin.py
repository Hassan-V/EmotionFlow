from datetime import datetime, timezone, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_admin
from app.core.redis import redis_client
from app.models.user import User, APIKey
from app.models.analysis import AnalysisJob
from app.models.billing import BillingEvent
from app.models.telemetry import APILog
from app.models.schemas import (
    TelemetrySummary, UserAdminView, UserQuotaUpdate, UserResponse, ErrorResponse,
)

logger = logging.getLogger("emotionflow.admin")
settings = get_settings()
router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(get_current_admin)])


@router.get("/telemetry", response_model=TelemetrySummary)
async def get_telemetry_summary(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    one_hour_ago = now - timedelta(hours=1)

    # Total requests (from Redis for speed)
    total_requests = int(await redis_client.get("telemetry:total_requests") or 0)
    error_count = int(await redis_client.get("telemetry:error_count") or 0)

    # User stats
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    active_today = (await db.execute(
        select(func.count(func.distinct(AnalysisJob.user_id))).where(
            AnalysisJob.created_at >= today_start
        )
    )).scalar() or 0

    # Job stats
    job_stats = (await db.execute(
        select(
            func.count(AnalysisJob.id).label("total"),
            func.count(case((AnalysisJob.status == "completed", 1))).label("completed"),
            func.count(case((AnalysisJob.status == "failed", 1))).label("failed"),
            func.count(case((AnalysisJob.status == "pending", 1))).label("pending"),
            func.avg(AnalysisJob.processing_time_ms).label("avg_time"),
        )
    )).one()

    # Requests last hour (from Redis stream)
    try:
        min_id = f"{int((one_hour_ago).timestamp() * 1000)}-0"
        entries = await redis_client.xrange("telemetry:api_logs", min=min_id)
        requests_last_hour = len(entries)
    except Exception:
        requests_last_hour = 0

    error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0.0

    return TelemetrySummary(
        total_requests=total_requests,
        total_users=total_users,
        active_users_today=active_today,
        total_analysis_jobs=job_stats.total,
        jobs_completed=job_stats.completed,
        jobs_failed=job_stats.failed,
        jobs_pending=job_stats.pending,
        avg_processing_time_ms=job_stats.avg_time,
        error_rate_percent=round(error_rate, 2),
        requests_last_hour=requests_last_hour,
    )


@router.get("/users", response_model=list[UserAdminView])
async def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            User,
            func.count(AnalysisJob.id).label("total_jobs"),
        )
        .outerjoin(AnalysisJob, User.id == AnalysisJob.user_id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    return [
        UserAdminView(
            id=user.id,
            email=user.email,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            quota_limit=user.quota_limit,
            quota_used_today=user.quota_used_today,
            total_jobs=total_jobs,
            created_at=user.created_at,
        )
        for user, total_jobs in rows
    ]


@router.patch("/users/{user_id}/quota", response_model=UserResponse)
async def update_user_quota(
    user_id: int,
    data: UserQuotaUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.quota_limit = data.quota_limit
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}/toggle-active", response_model=UserResponse)
async def toggle_user_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/logs")
async def get_recent_logs(
    count: int = Query(default=100, ge=1, le=1000),
):
    """Get recent API logs from Redis stream (real-time, no DB query)."""
    try:
        entries = await redis_client.xrevrange("telemetry:api_logs", count=count)
        logs = []
        for entry_id, data in entries:
            data["id"] = entry_id
            logs.append(data)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        logger.error(f"Failed to read telemetry logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to read logs")


@router.get("/jobs/stats")
async def get_worker_job_stats(
    count: int = Query(default=200, ge=1, le=1000),
):
    """Get recent worker pipeline stats from Redis stream (stage-level timings)."""
    try:
        entries = await redis_client.xrevrange("telemetry:worker_jobs", count=count)
        jobs = []
        for entry_id, data in entries:
            data["id"] = entry_id
            jobs.append(data)

        def _f(val, default=0.0):
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        completed = [j for j in jobs if j.get("status") == "completed"]
        failed = [j for j in jobs if j.get("status") == "failed"]
        n = len(completed)

        return {
            "recent_jobs": jobs,
            "summary": {
                "total": len(jobs),
                "completed": n,
                "failed": len(failed),
                "avg_total_ms": round(sum(_f(j.get("total_time_ms")) for j in completed) / n, 1) if n else 0.0,
                "avg_asr_ms": round(sum(_f(j.get("asr_time_ms")) for j in completed) / n, 1) if n else 0.0,
                "avg_emotion_ms": round(sum(_f(j.get("emotion_time_ms")) for j in completed) / n, 1) if n else 0.0,
                "avg_gemini_ms": round(sum(_f(j.get("gemini_time_ms")) for j in completed) / n, 1) if n else 0.0,
            },
        }
    except Exception as e:
        logger.error(f"Failed to read worker job stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to read job stats")


@router.get("/billing/summary")
async def get_billing_summary(
    year: int = Query(default=None, description="Year (default: current year)"),
    month: int = Query(default=None, ge=1, le=12, description="Month 1-12 (default: current month)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Billing summary from the immutable BillingEvent ledger.

    Provides per-user and per-API-key breakdowns for the given month.
    Source of truth for dispute resolution — records are never modified.

    Tier rates (USD per completed job):
      fast=$0.001  balanced=$0.005  max=$0.020
    Failed jobs are recorded at cost=$0.00.
    """
    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month

    period_start = datetime(year, month, 1, tzinfo=timezone.utc)
    period_end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    )
    tier_costs = {
        "fast": settings.TIER_COST_FAST,
        "balanced": settings.TIER_COST_BALANCED,
        "max": settings.TIER_COST_MAX,
    }

    # ── Per-user aggregates from BillingEvent ────────────────────
    rows = await db.execute(
        select(
            BillingEvent.user_id,
            BillingEvent.model_tier,
            BillingEvent.status,
            func.count(BillingEvent.id).label("job_count"),
            func.sum(BillingEvent.cost_usd).label("total_cost"),
        )
        .where(
            BillingEvent.occurred_at >= period_start,
            BillingEvent.occurred_at < period_end,
        )
        .group_by(BillingEvent.user_id, BillingEvent.model_tier, BillingEvent.status)
    )
    aggregates = rows.all()

    # ── Per-key aggregates ───────────────────────────────────────
    key_rows = await db.execute(
        select(
            BillingEvent.api_key_id,
            BillingEvent.user_id,
            func.count(BillingEvent.id).label("job_count"),
            func.sum(BillingEvent.cost_usd).label("total_cost"),
        )
        .where(
            BillingEvent.occurred_at >= period_start,
            BillingEvent.occurred_at < period_end,
            BillingEvent.api_key_id.isnot(None),
        )
        .group_by(BillingEvent.api_key_id, BillingEvent.user_id)
    )
    key_aggregates = key_rows.all()

    # ── Load usernames / key names ───────────────────────────────
    user_ids = list({row.user_id for row in aggregates if row.user_id})
    key_ids = list({row.api_key_id for row in key_aggregates if row.api_key_id})

    users_by_id = {}
    if user_ids:
        ur = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in ur.scalars().all()}

    keys_by_id = {}
    if key_ids:
        kr = await db.execute(select(APIKey).where(APIKey.id.in_(key_ids)))
        keys_by_id = {k.id: k for k in kr.scalars().all()}

    # ── Build per-user structure ─────────────────────────────────
    by_user: dict[int, dict] = {}
    for row in aggregates:
        uid = row.user_id
        if uid not in by_user:
            u = users_by_id.get(uid)
            by_user[uid] = {
                "user_id": uid,
                "username": u.username if u else "deleted",
                "email": u.email if u else "deleted",
                "jobs_completed": 0,
                "jobs_failed": 0,
                "total_cost_usd": 0.0,
                "tier_breakdown": {},
            }
        tier = row.model_tier or "balanced"
        cost = float(row.total_cost or 0)
        slot = by_user[uid]["tier_breakdown"].setdefault(tier, {"completed": 0, "failed": 0, "cost_usd": 0.0})
        slot["cost_usd"] = round(slot["cost_usd"] + cost, 6)
        if row.status == "completed":
            by_user[uid]["jobs_completed"] += row.job_count
            slot["completed"] += row.job_count
        else:
            by_user[uid]["jobs_failed"] += row.job_count
            slot["failed"] += row.job_count
        by_user[uid]["total_cost_usd"] = round(by_user[uid]["total_cost_usd"] + cost, 6)

    # ── Build per-key structure ───────────────────────────────────
    by_key = []
    for row in key_aggregates:
        k = keys_by_id.get(row.api_key_id)
        by_key.append({
            "api_key_id": row.api_key_id,
            "key_prefix": k.key_prefix if k else "deleted",
            "key_name": k.name if k else "deleted",
            "usage_count_total": k.usage_count if k else None,   # all-time from APIKey table
            "user_id": row.user_id,
            "jobs_this_period": row.job_count,
            "cost_usd_this_period": round(float(row.total_cost or 0), 6),
        })
    by_key.sort(key=lambda x: x["cost_usd_this_period"], reverse=True)

    sorted_users = sorted(by_user.values(), key=lambda x: x["total_cost_usd"], reverse=True)
    total_cost = round(sum(u["total_cost_usd"] for u in sorted_users), 6)

    return {
        "period": f"{year}-{month:02d}",
        "total_cost_usd": total_cost,
        "tier_rates_usd": tier_costs,
        "by_user": sorted_users,
        "by_api_key": by_key,
    }

