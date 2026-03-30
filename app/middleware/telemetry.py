import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.redis import redis_client

logger = logging.getLogger("emotionflow.telemetry")


class TelemetryMiddleware(BaseHTTPMiddleware):
    """
    Non-blocking telemetry middleware.
    Logs request metrics to Redis (fast), which get flushed to PostgreSQL
    by a periodic background task. This avoids blocking the request cycle
    with DB writes.
    """

    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start_time = time.perf_counter()
        response = None
        error_detail = None

        try:
            response = await call_next(request)
        except Exception as exc:
            error_detail = str(exc)[:500]
            raise

        process_time_ms = (time.perf_counter() - start_time) * 1000
        status_code = response.status_code if response else 500

        # Inject timing header
        if response:
            response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"

        # Extract user_id from request state if auth set it
        user_id = getattr(request.state, "user_id", None)

        log_entry = {
            "user_id": str(user_id) if user_id else "",
            "path": request.url.path,
            "method": request.method,
            "status_code": str(status_code),
            "process_time_ms": f"{process_time_ms:.2f}",
            "client_ip": request.client.host if request.client else "",
            "user_agent": (request.headers.get("user-agent", ""))[:500],
            "error_detail": error_detail or "",
        }

        # Fire-and-forget to Redis — does NOT block the response
        try:
            await redis_client.xadd(
                "telemetry:api_logs",
                log_entry,
                maxlen=50000,
            )
            await redis_client.incr("telemetry:total_requests")
            if status_code >= 400:
                await redis_client.incr("telemetry:error_count")
            if user_id:
                await redis_client.incr(f"telemetry:user:{user_id}:requests")
        except Exception as redis_err:
            logger.warning(f"Telemetry Redis write failed: {redis_err}")

        return response
