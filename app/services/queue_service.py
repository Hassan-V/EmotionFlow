import json
import logging
from typing import Optional
from app.core.redis import redis_client

logger = logging.getLogger("emotionflow.queue")

QUEUE_NAME = "analysis:jobs"


async def enqueue_analysis_job(
    job_id: str, filename: str, model_tier: str,
    user_id: int = 0, session_id: str = "",
    api_key_id: Optional[int] = None,
):
    """Push an analysis job onto the Redis queue for worker consumption."""
    payload = json.dumps({
        "job_id": job_id,
        "filename": filename,
        "model_tier": model_tier,
        "user_id": user_id,
        "session_id": session_id,
        "api_key_id": api_key_id,
    })
    await redis_client.lpush(QUEUE_NAME, payload)
    logger.info(f"Enqueued job {job_id} (tier={model_tier})")


async def dequeue_analysis_job(timeout: int = 5) -> Optional[dict]:
    """Blocking pop from the job queue. Returns job dict or None."""
    result = await redis_client.brpop(QUEUE_NAME, timeout=timeout)
    if result:
        _, payload = result
        return json.loads(payload)
    return None
