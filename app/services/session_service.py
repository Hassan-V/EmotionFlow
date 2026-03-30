"""
Session Memory Service — Redis-backed conversation context persistence.

Stores session context so Gemini can maintain awareness across multiple
analysis requests within the same conversation / user session.

Storage model:
  - Key: session:{user_id}:{session_id}
  - Value: JSON with rolling context (summary of previous analyses)
  - TTL: 24 hours by default (configurable)

This allows long conversations to build up context that Gemini references
when explaining emotional causality, detecting patterns, and tracking
emotional arcs across multiple audio submissions.
"""
import json
import logging
import time
from typing import Optional

import redis

logger = logging.getLogger("emotionflow.session")

SESSION_PREFIX = "session:"
DEFAULT_TTL_SECONDS = 86400  # 24 hours
MAX_CONTEXT_ENTRIES = 50  # Keep last N analysis summaries


def _session_key(user_id: int, session_id: str) -> str:
    return f"{SESSION_PREFIX}{user_id}:{session_id}"


def get_session_context(
    redis_client: redis.Redis,
    user_id: int,
    session_id: str,
) -> Optional[str]:
    """
    Retrieve the accumulated session context for Gemini.

    Returns a formatted string of previous analysis summaries,
    or None if no session exists.
    """
    key = _session_key(user_id, session_id)
    raw = redis_client.get(key)
    if not raw:
        return None

    data = json.loads(raw)
    entries = data.get("entries", [])
    if not entries:
        return None

    # Build context string from entries
    lines = [f"=== Session Context ({len(entries)} previous analyses) ==="]
    for entry in entries[-10:]:  # Last 10 for context window size management
        lines.append(f"\n--- Analysis at {entry.get('timestamp', 'unknown')} ---")
        lines.append(entry.get("summary", ""))

    return "\n".join(lines)


def append_to_session(
    redis_client: redis.Redis,
    user_id: int,
    session_id: str,
    summary: str,
    metadata: Optional[dict] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
):
    """
    Append a new analysis summary to the session context.

    Args:
        redis_client: Sync redis client
        user_id: Owner user ID
        session_id: Session identifier (from client or job)
        summary: Text summary from gemini_service.build_session_summary()
        metadata: Optional extra data (job_id, filename, etc.)
        ttl_seconds: Time-to-live for the session
    """
    key = _session_key(user_id, session_id)
    raw = redis_client.get(key)

    if raw:
        data = json.loads(raw)
    else:
        data = {"user_id": user_id, "session_id": session_id, "entries": []}

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "summary": summary,
    }
    if metadata:
        entry["metadata"] = metadata

    data["entries"].append(entry)

    # Trim to max entries
    if len(data["entries"]) > MAX_CONTEXT_ENTRIES:
        data["entries"] = data["entries"][-MAX_CONTEXT_ENTRIES:]

    redis_client.set(key, json.dumps(data), ex=ttl_seconds)
    logger.info(f"Session {session_id}: appended entry ({len(data['entries'])} total)")


def clear_session(
    redis_client: redis.Redis,
    user_id: int,
    session_id: str,
):
    """Delete a session's context."""
    key = _session_key(user_id, session_id)
    redis_client.delete(key)
    logger.info(f"Session {session_id}: cleared")


def list_sessions(
    redis_client: redis.Redis,
    user_id: int,
) -> list[dict]:
    """List all active sessions for a user."""
    pattern = f"{SESSION_PREFIX}{user_id}:*"
    sessions = []
    for key in redis_client.scan_iter(match=pattern, count=100):
        if isinstance(key, bytes):
            key = key.decode()
        raw = redis_client.get(key)
        if raw:
            data = json.loads(raw)
            session_id = key.split(":")[-1]
            sessions.append({
                "session_id": session_id,
                "entries_count": len(data.get("entries", [])),
                "last_updated": data["entries"][-1]["timestamp"] if data.get("entries") else None,
            })
    return sessions
