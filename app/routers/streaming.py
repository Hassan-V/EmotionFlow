"""Authenticated WebSocket gateway for Tailscale GPU live workers."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import get_settings

logger = logging.getLogger("emotionflow.streaming")
router = APIRouter(tags=["Streaming"])
settings = get_settings()

SESSION_TTL_SECONDS = 900


async def _authenticate(token: str):
    if not token:
        return None
    try:
        from app.core.database import AsyncSessionLocal
        from app.core.security import decode_token
        from app.models.user import User

        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("Live authentication failed: %s", exc)
        return None


async def _select_live_worker(redis_client) -> str | None:
    workers = sorted(await redis_client.keys("live-worker:heartbeat:*"))
    if not workers:
        return None
    return workers[0].split("live-worker:heartbeat:", 1)[1]


async def _enqueue(redis_client, worker_id: str, message: dict):
    key = f"live:worker:{worker_id}"
    await redis_client.rpush(key, json.dumps(message))
    await redis_client.expire(key, SESSION_TTL_SECONDS)


async def _persist_live_result(user_id: int, session_id: str, result: dict) -> None:
    """Store a completed live session in the same history used by file jobs."""
    from app.core.database import AsyncSessionLocal
    from app.models.analysis import AnalysisJob

    completed_at = datetime.now(timezone.utc)
    duration_seconds = float(result.get("duration_seconds") or 0)
    processing_time_ms = float(result.get("processing_time_ms") or 0)
    started_at = completed_at - timedelta(milliseconds=max(0, processing_time_ms))
    async with AsyncSessionLocal() as db:
        db.add(AnalysisJob(
            job_id=session_id,
            user_id=user_id,
            filename=f"live-{session_id[:8]}.pcm",
            file_path="",
            file_size_bytes=max(0, int(duration_seconds * 16000 * 2)),
            audio_format="pcm_s16le",
            model_tier="fast",
            status="completed",
            result=result,
            duration_seconds=duration_seconds,
            overall_sentiment=result.get("overall_sentiment"),
            started_at=started_at,
            completed_at=completed_at,
            processing_time_ms=processing_time_ms,
        ))
        await db.commit()


@router.websocket("/ws/stream")
async def stream_analysis(websocket: WebSocket, token: str = Query(default="")):
    user = await _authenticate(token)
    await websocket.accept()
    if not user:
        await websocket.send_json({"type": "error", "message": "Authentication required", "recoverable": False})
        await websocket.close(code=4001)
        return

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    worker_id = await _select_live_worker(redis_client)
    if not worker_id:
        await websocket.send_json({
            "type": "error",
            "message": "No live GPU worker is available. Start app.services.live_worker on a Tailscale worker.",
            "recoverable": True,
        })
        await websocket.close(code=1013)
        await redis_client.aclose()
        return

    session_id = str(uuid.uuid4())
    result_channel = f"live:result:{session_id}"
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(result_channel)
    await websocket.send_json({
        "type": "connected", "session_id": session_id, "worker_id": worker_id,
        "protocol": {"encoding": "pcm_s16le", "sample_rate": 16000, "chunk_ms": 250},
    })

    async def receive_audio():
        configured = False
        sequence = 0
        audio_buffer = bytearray()
        while True:
            event = await asyncio.wait_for(websocket.receive(), timeout=SESSION_TTL_SECONDS)
            if event["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(event.get("code", 1000))
            if event.get("text") is not None:
                try:
                    message = json.loads(event["text"])
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid control JSON", "recoverable": True})
                    continue
                kind = message.get("type")
                if kind == "config":
                    expected = {
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                        "chunk_ms": 250,
                    }
                    invalid = [key for key, value in expected.items() if message.get(key) != value]
                    if invalid:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Unsupported stream config: {', '.join(invalid)}",
                            "recoverable": True,
                        })
                        continue
                    configured = True
                    await _enqueue(redis_client, worker_id, {
                        "type": "start", "session_id": session_id, "user_id": user.id,
                        "tier": "fast", "client_session_id": message.get("session_id", ""),
                        "captured_at_ms": int(time.time() * 1000),
                    })
                    await websocket.send_json({"type": "status", "message": "Live GPU worker ready"})
                elif kind == "end_stream":
                    if audio_buffer:
                        sequence += 1
                        await _enqueue(redis_client, worker_id, {
                            "type": "audio", "session_id": session_id, "sequence": sequence,
                            "captured_at_ms": int(time.time() * 1000),
                            "data": base64.b64encode(bytes(audio_buffer)).decode("ascii"),
                        })
                        audio_buffer.clear()
                    await _enqueue(redis_client, worker_id, {"type": "end", "session_id": session_id})
                    return
                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown control type: {kind}", "recoverable": True})
            elif event.get("bytes") is not None:
                if not configured:
                    await websocket.send_json({"type": "error", "message": "Send config before audio", "recoverable": True})
                    continue
                audio_buffer.extend(event["bytes"])
                if len(audio_buffer) >= 32000:
                    sequence += 1
                    await _enqueue(redis_client, worker_id, {
                        "type": "audio", "session_id": session_id, "sequence": sequence,
                        "captured_at_ms": int(time.time() * 1000),
                        "data": base64.b64encode(bytes(audio_buffer)).decode("ascii"),
                    })
                    audio_buffer.clear()

    async def forward_results():
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                if not await redis_client.exists(f"live-worker:heartbeat:{worker_id}"):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Live GPU worker was lost; reconnect to resume analysis.",
                        "recoverable": True,
                    })
                    return
                await asyncio.sleep(0.02)
                continue
            payload = json.loads(message["data"])
            captured_at_ms = payload.pop("captured_at_ms", None)
            if captured_at_ms is not None:
                payload["latency_ms"] = max(
                    0, int(time.time() * 1000) - int(captured_at_ms)
                )
            if payload.get("type") == "final_result":
                try:
                    await _persist_live_result(user.id, session_id, payload["result"])
                except Exception as exc:
                    logger.exception("Could not persist live result %s: %s", session_id, exc)
            await websocket.send_json(payload)
            if payload.get("type") in ("final_result", "fatal"):
                return

    receiver = asyncio.create_task(receive_audio())
    forwarder = asyncio.create_task(forward_results())
    try:
        done, pending = await asyncio.wait({receiver, forwarder}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exception = task.exception()
            if exception:
                raise exception
        if receiver in done:
            await asyncio.wait_for(forwarder, timeout=30)
        else:
            receiver.cancel()
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        await _enqueue(redis_client, worker_id, {"type": "cancel", "session_id": session_id})
    except Exception as exc:
        logger.error("Live gateway error for %s: %s", session_id, exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc), "recoverable": True})
        except Exception:
            pass
    finally:
        receiver.cancel()
        forwarder.cancel()
        try:
            await _enqueue(redis_client, worker_id, {"type": "cancel", "session_id": session_id})
        except Exception:
            pass
        await pubsub.unsubscribe(result_channel)
        await pubsub.aclose()
        await redis_client.aclose()
        try:
            await websocket.close()
        except Exception:
            pass
