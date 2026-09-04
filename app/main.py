import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine, Base
from app.core.redis import redis_client
from app.middleware.telemetry import TelemetryMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import auth, analysis, api_keys, admin, streaming, webhooks, internal

# Import all models so Base.metadata knows about them
from app.models.user import User, APIKey  # noqa: F401
from app.models.analysis import AnalysisJob  # noqa: F401
from app.models.telemetry import APILog  # noqa: F401
from app.models.webhook import Webhook, WebhookDelivery  # noqa: F401
from app.models.billing import BillingEvent  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emotionflow")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent compatibility migration for databases created before auth v2.
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_test_account BOOLEAN NOT NULL DEFAULT false"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"
        ))
        await conn.execute(text(
            "ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS compute_units INTEGER NOT NULL DEFAULT 0"
        ))
        # Legacy deployments used a mandatory cost_usd column. Keep it
        # readable, but give new compute-unit ledger writes a safe default.
        await conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'billing_events' AND column_name = 'cost_usd'
                ) THEN
                    ALTER TABLE billing_events ALTER COLUMN cost_usd SET DEFAULT 0.0;
                END IF;
            END $$
        """))
    logger.info("Database tables ready.")

    # Verify Redis connection
    try:
        await redis_client.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")

    yield

    # Shutdown
    await engine.dispose()
    await redis_client.aclose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="EmotionFlow API",
    description="Temporal Emotion Profiling & Causal Analysis API",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── Middleware (order matters: last added = first executed) ──────

app.add_middleware(TelemetryMiddleware)
app.add_middleware(RateLimitMiddleware)
# Build CORS origins from env (production) + dev defaults
_cors_origins = ["http://localhost:5173", "http://localhost:3000"]
if settings.CORS_ORIGINS:
    _cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(api_keys.router)
app.include_router(admin.router)
app.include_router(streaming.router)
app.include_router(webhooks.router)
app.include_router(internal.router)


# ─── Global exception handler ─────────────────────────────────────
# Catches any unhandled exception and returns a generic 500.
# The real error is logged internally (Redis + Python logger) but
# NEVER exposed in the response body — nothing leaks to the user layer.

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}\n"
        f"Path: {request.method} {request.url.path}\n{tb}"
    )
    # Best-effort telemetry — do not let this block the error response
    try:
        user_id = getattr(request.state, "user_id", None)
        await redis_client.xadd(
            "telemetry:api_logs",
            {
                "user_id": str(user_id) if user_id else "",
                "path": request.url.path,
                "method": request.method,
                "status_code": "500",
                "process_time_ms": "0",
                "client_ip": request.client.host if request.client else "",
                "user_agent": (request.headers.get("user-agent", ""))[:200],
                "error_detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            },
            maxlen=50000,
        )
        await redis_client.incr("telemetry:error_count")
    except Exception:
        pass

    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )


@app.get("/health", tags=["Health"])
async def health_check():
    # Check DB
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Check Redis
    redis_ok = False
    live_workers = 0
    try:
        await redis_client.ping()
        redis_ok = True
        live_workers = len(await redis_client.keys("live-worker:heartbeat:*"))
    except Exception:
        pass

    status = "healthy" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
        "live_workers_ready": live_workers,
        "version": "1.0.0",
    }
