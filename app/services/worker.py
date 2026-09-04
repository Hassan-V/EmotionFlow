"""
AI Worker Process — Runs separately from the API.
Pulls jobs from Redis queue, processes audio files through the real AI pipeline:
  1. ASR → transcript with timestamps
  2. Text + audio emotion classification, acoustic analysis and local fusion
  3. Local topic/shift detection + Qwen causal explanations
  4. Session memory → persist context for multi-turn analysis

Writes structured results back to PostgreSQL.
"""
import asyncio
import json
import logging
import os
import tempfile
import time
import sys
from datetime import datetime, timezone

import redis
import requests
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("emotionflow.worker")


def get_sync_db():
    from app.core.config import get_settings
    settings = get_settings()
    engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
    return sessionmaker(bind=engine)


def get_sync_redis():
    from app.core.config import get_settings
    settings = get_settings()
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _download_audio(filename: str, dest_dir: str) -> str:
    """Download audio file from API's internal endpoint. Returns local path."""
    from app.core.config import get_settings
    settings = get_settings()

    url = f"{settings.API_BASE_URL}/internal/files/{filename}"
    resp = requests.get(
        url,
        headers={"X-Worker-Secret": settings.WORKER_SECRET},
        timeout=120,
    )
    resp.raise_for_status()

    local_path = os.path.join(dest_dir, filename)
    with open(local_path, "wb") as f:
        f.write(resp.content)
    return local_path


def process_audio_file(
    file_path: str,
    model_tier: str,
    user_id: int = 0,
    session_id: str = "",
    redis_client: redis.Redis = None,
) -> dict:
    """
    Real AI pipeline:
      1. Whisper ASR → transcript segments
      2. Text + audio emotion recognition → canonical fused labels
      3. Local topic/shift evidence → grounded local causal reasoning
      4. Session memory → persist context

    Returns structured AnalysisResult dict.
    """
    from app.services.asr_service import transcribe
    from app.services.multimodal_service import analyze_multimodal_segments
    from app.services.local_causality_service import MODEL_NAME, build_session_summary, build_summary
    from app.services import session_service

    logger.info(f"Processing {file_path} with tier={model_tier}")

    # ── Step 1: ASR (Whisper) ────────────────────────────────────
    logger.info("Step 1/3: Running Whisper ASR...")
    _t0 = time.perf_counter()
    asr_result = transcribe(file_path, tier=model_tier)
    asr_time_ms = (time.perf_counter() - _t0) * 1000
    transcript_segments = asr_result["segments"]
    segments = transcript_segments
    duration = asr_result["duration_seconds"]
    if not segments and duration > 0:
        # Preserve audio-only emotion analysis when no text can be transcribed.
        segments = [{"start": 0.0, "end": duration, "text": ""}]
    logger.info(f"ASR done: {len(segments)} segments, {duration:.1f}s audio, lang={asr_result['language']}, took {asr_time_ms:.0f}ms")

    # ── Step 2: Unified multimodal analysis ───────────────────────
    logger.info("Step 2/3: Running text + audio fusion, topics and local causality...")
    _t0 = time.perf_counter()
    multimodal = analyze_multimodal_segments(segments, file_path, tier=model_tier)
    classified = multimodal["segments"]
    emotion_time_ms = (time.perf_counter() - _t0) * 1000
    logger.info(f"Multimodal analysis done: {len(classified)} segments, took {emotion_time_ms:.0f}ms")
    _summary_started = time.perf_counter()
    final_summary = build_summary(classified, multimodal["transitions"], use_model=True)
    local_causality_time_ms = (
        multimodal.get("stage_timings", {}).get("local_causality_time_ms", 0)
        + (time.perf_counter() - _summary_started) * 1000
    )
    multimodal["summary"] = final_summary

    # ── Step 4: Session Memory ───────────────────────────────────
    if redis_client and session_id:
        summary = build_session_summary(classified, multimodal)
        session_service.append_to_session(
            redis_client, user_id, session_id, summary,
            metadata={"filename": os.path.basename(file_path)},
        )

    # ── Build final result ───────────────────────────────────────
    # Preserve the established timeline fields and add auditable provenance.
    timeline = []
    for seg in classified:
        timeline.append({
            "timestamp_start": seg["start"],
            "timestamp_end": seg["end"],
            "text": seg["text"],
            "emotion": seg["emotion"],
            "intensity": round(float(seg["intensity"]), 4),
            "trigger_phrase": seg.get("trigger_phrase"),
            "cause": seg.get("cause"),
            "cause_source": seg.get("cause_source"),
            "modalities": seg.get("modalities", {}),
            "topic": seg.get("topic", {}),
            "acoustic": seg.get("acoustic", {}),
        })

    transcript = [
        {
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "speaker": "Speaker 1",  # TODO: diarization in future
        }
        for seg in transcript_segments
    ]

    return {
        "filename": os.path.basename(file_path),
        "duration_seconds": duration,
        "overall_sentiment": multimodal["overall_sentiment"],
        "model_tier": model_tier,
        "language": asr_result.get("language", "en"),
        "summary": final_summary,
        "timeline": timeline,
        "transcript": transcript,
        "transitions": multimodal["transitions"],
        "model_provenance": {
            "asr": asr_result.get("model"),
            "audio_emotion": "superb/wav2vec2-base-superb-er",
            "text_emotion": "j-hartmann/emotion-english-distilroberta-base",
            "fusion": "weighted-audio-0.55-text-0.45",
            "causality": f"{MODEL_NAME} with deterministic fallback",
            "external_inference": False,
        },
        "stage_timings": {
            "asr_time_ms": round(asr_time_ms, 1),
            "emotion_time_ms": round(emotion_time_ms, 1),
            "local_causality_time_ms": round(local_causality_time_ms, 1),
        },
    }


# ── Tier compute unit map (must stay in sync with config.py TIER_CU_* values) ─
_TIER_CU = {"fast": 1, "balanced": 5, "max": 20}


def _write_billing_event(
    SessionLocal,
    job_id: str,
    user_id: int,
    api_key_id,
    model_tier: str,
    status: str,
    processing_time_ms: float,
    audio_duration_s,
    file_size_bytes,
    cu_override: int = None,
):
    """
    Write one immutable BillingEvent row.
    Called after every job — success and failure — for the audit ledger.
    Failed jobs record compute_units=0 (no charge for failures).
    """
    from app.models.billing import BillingEvent
    cu = cu_override if cu_override is not None else _TIER_CU.get(model_tier, 5)
    try:
        with SessionLocal() as db:
            event = BillingEvent(
                job_id=job_id,
                user_id=user_id or None,
                api_key_id=api_key_id,
                model_tier=model_tier,
                file_size_bytes=file_size_bytes,
                audio_duration_s=audio_duration_s,
                status=status,
                processing_time_ms=processing_time_ms,
                compute_units=cu,
            )
            db.add(event)
            db.commit()
        logger.info(f"BillingEvent written: job={job_id} tier={model_tier} cu={cu} status={status}")
    except Exception as be:
        logger.error(f"Failed to write BillingEvent for job {job_id}: {be}")


async def worker_loop():
    """Main worker loop — pulls jobs from Redis and processes them."""
    import redis.asyncio as aioredis
    import socket
    from app.core.config import get_settings

    # Import all ORM models upfront so SQLAlchemy can configure all mappers
    # (AnalysisJob has relationship("User") which must be resolved before any update)
    from app.models.analysis import AnalysisJob  # noqa: F401
    from app.models.user import User, APIKey  # noqa: F401
    from app.models.webhook import Webhook, WebhookDelivery  # noqa: F401
    from app.models.billing import BillingEvent  # noqa: F401

    settings = get_settings()
    async_redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    sync_redis = get_sync_redis()
    SessionLocal = get_sync_db()

    # Stable worker ID for this process lifetime
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    HEARTBEAT_KEY = f"worker:heartbeat:{worker_id}"
    HEARTBEAT_TTL = 30  # seconds — if no heartbeat for 30s, considered dead
    gpu_resource = os.getenv("GPU_RESOURCE_ID", "default-gpu")
    live_priority_key = f"gpu:{gpu_resource}:live-priority"

    logger.info(f"Worker started (id={worker_id}). Warming local causal model before accepting jobs...")
    try:
        from app.services.local_causality_service import MODEL_NAME, _load_qwen
        await asyncio.to_thread(_load_qwen)
        logger.info("Causality engine ready: %s (no external inference)", MODEL_NAME)
    except Exception as exc:
        logger.warning("Local causal model warmup failed; grounded fallback remains available: %s", exc)
    logger.info("Waiting for jobs...")

    while True:
        try:
            # Heartbeat — mark this worker as alive with a 30s TTL
            await async_redis.setex(HEARTBEAT_KEY, HEARTBEAT_TTL, int(time.time()))

            if await async_redis.exists(live_priority_key):
                await asyncio.sleep(0.25)
                continue

            # Stay below common five-second network read timeouts on remote Redis links.
            result = await async_redis.brpop("analysis:jobs", timeout=2)
            if not result:
                continue

            _, payload_str = result
            if await async_redis.exists(live_priority_key):
                await async_redis.rpush("analysis:jobs", payload_str)
                await asyncio.sleep(0.25)
                continue
            payload = json.loads(payload_str)

            job_id = payload["job_id"]
            filename = payload["filename"]
            model_tier = payload["model_tier"]
            user_id = payload.get("user_id", 0)
            session_id = payload.get("session_id", "")
            api_key_id = payload.get("api_key_id")  # None if JWT auth was used

            logger.info(f"Picked up job {job_id} (tier={model_tier}, user={user_id})")

            # Mark as processing
            with SessionLocal() as db:
                db.execute(
                    update(AnalysisJob)
                    .where(AnalysisJob.job_id == job_id)
                    .values(status="processing", started_at=datetime.now(timezone.utc))
                )
                db.commit()

            # Download audio from API (supports remote worker over Tailscale)
            tmp_dir = tempfile.mkdtemp(prefix="emotionflow_")
            file_path = None
            try:
                file_path = _download_audio(filename, tmp_dir)
                logger.info(f"Downloaded {filename} to {file_path}")
            except Exception as dl_err:
                logger.error(f"Failed to download audio for job {job_id}: {dl_err}")
                with SessionLocal() as db:
                    db.execute(
                        update(AnalysisJob)
                        .where(AnalysisJob.job_id == job_id)
                        .values(
                            status="failed",
                            error_message=f"Audio download failed: {dl_err}"[:1000],
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                    db.commit()
                continue

            # Run the real AI pipeline
            start_time = time.perf_counter()
            try:
                result_data = process_audio_file(
                    file_path=file_path,
                    model_tier=model_tier,
                    user_id=user_id,
                    session_id=session_id,
                    redis_client=sync_redis,
                )
                processing_time_ms = (time.perf_counter() - start_time) * 1000

                result_data["processing_time_ms"] = processing_time_ms

                with SessionLocal() as db:
                    db.execute(
                        update(AnalysisJob)
                        .where(AnalysisJob.job_id == job_id)
                        .values(
                            status="completed",
                            result=result_data,
                            duration_seconds=result_data.get("duration_seconds"),
                            overall_sentiment=result_data.get("overall_sentiment"),
                            processing_time_ms=processing_time_ms,
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                    db.commit()

                logger.info(f"Job {job_id} completed in {processing_time_ms:.0f}ms")

                # Write immutable billing record
                _write_billing_event(
                    SessionLocal, job_id=job_id, user_id=user_id,
                    api_key_id=api_key_id, model_tier=model_tier,
                    status="completed",
                    processing_time_ms=processing_time_ms,
                    audio_duration_s=result_data.get("duration_seconds"),
                    file_size_bytes=result_data.get("file_size_bytes"),
                )

                # Push structured pipeline telemetry to Redis stream
                try:
                    stage_timings = result_data.get("stage_timings", {})
                    sync_redis.xadd(
                        "telemetry:worker_jobs",
                        {
                            "job_id": str(job_id),
                            "user_id": str(user_id),
                            "model_tier": model_tier or "",
                            "status": "completed",
                            "total_time_ms": str(round(processing_time_ms, 1)),
                            "asr_time_ms": str(stage_timings.get("asr_time_ms", 0)),
                            "emotion_time_ms": str(stage_timings.get("emotion_time_ms", 0)),
                            "local_causality_time_ms": str(stage_timings.get("local_causality_time_ms", 0)),
                            "segment_count": str(len(result_data.get("timeline", []))),
                            "audio_duration_s": str(round(result_data.get("duration_seconds", 0), 2)),
                            "overall_sentiment": result_data.get("overall_sentiment", ""),
                            "ts": str(int(time.time() * 1000)),
                        },
                        maxlen=10000,
                        approximate=True,
                    )
                except Exception as _te:
                    logger.warning(f"Failed to push job telemetry: {_te}")

                # Publish webhook event
                try:
                    from app.services.webhook_service import publish_event_sync
                    publish_event_sync(
                        sync_redis, "job.completed", job_id, user_id,
                        data={
                            "status": "completed",
                            "processing_time_ms": processing_time_ms,
                            "overall_sentiment": result_data.get("overall_sentiment"),
                            "duration_seconds": result_data.get("duration_seconds"),
                            "model_tier": model_tier,
                        },
                    )
                except Exception as we:
                    logger.warning(f"Failed to publish webhook event: {we}")

            except Exception as e:
                processing_time_ms = (time.perf_counter() - start_time) * 1000
                logger.error(f"Job {job_id} failed: {e}")

                # Push failure telemetry to Redis stream
                try:
                    sync_redis.xadd(
                        "telemetry:worker_jobs",
                        {
                            "job_id": str(job_id),
                            "user_id": str(user_id),
                            "model_tier": model_tier or "",
                            "status": "failed",
                            "total_time_ms": str(round(processing_time_ms, 1)),
                            "ts": str(int(time.time() * 1000)),
                        },
                        maxlen=10000,
                        approximate=True,
                    )
                except Exception as _te:
                    logger.warning(f"Failed to push job telemetry: {_te}")

                with SessionLocal() as db:
                    db.execute(
                        update(AnalysisJob)
                        .where(AnalysisJob.job_id == job_id)
                        .values(
                            status="failed",
                            error_message=str(e)[:1000],
                            processing_time_ms=processing_time_ms,
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                    db.commit()

                # Write immutable billing record for failed jobs too (they consumed quota)
                _write_billing_event(
                    SessionLocal, job_id=job_id, user_id=user_id,
                    api_key_id=api_key_id, model_tier=model_tier,
                    status="failed",
                    processing_time_ms=processing_time_ms,
                    audio_duration_s=None,
                    file_size_bytes=None,
                    cu_override=0,  # failed jobs don't consume CU
                )

                # Publish webhook event for failure
                try:
                    from app.services.webhook_service import publish_event_sync
                    publish_event_sync(
                        sync_redis, "job.failed", job_id, user_id,
                        data={
                            "status": "failed",
                            "error": str(e)[:500],
                            "processing_time_ms": processing_time_ms,
                            "model_tier": model_tier,
                        },
                    )
                except Exception as we:
                    logger.warning(f"Failed to publish webhook event: {we}")

            finally:
                # Clean up downloaded audio
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(2)


def main():
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
