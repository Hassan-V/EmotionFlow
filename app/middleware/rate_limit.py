import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from app.core.redis import redis_client
from app.core.config import get_settings

logger = logging.getLogger("emotionflow.ratelimit")
settings = get_settings()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token-bucket style rate limiting using Redis.
    Limits per client IP for unauthenticated, per user_id for authenticated requests.
    """

    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Determine rate limit key
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            key = f"ratelimit:user:{user_id}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = f"ratelimit:ip:{client_ip}"

        try:
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, 60)  # 1-minute window

            if current > settings.RATE_LIMIT_PER_MINUTE:
                ttl = await redis_client.ttl(key)
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded. Try again in {ttl}s."},
                    headers={"Retry-After": str(ttl)},
                )
        except Exception as redis_err:
            # If Redis is down, allow the request through (fail-open)
            logger.warning(f"Rate limit Redis check failed: {redis_err}")

        response = await call_next(request)
        return response
