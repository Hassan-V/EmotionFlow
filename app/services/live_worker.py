"""Low-latency PCM processor running on a Tailscale GPU worker."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import tempfile
import time
from dataclasses import dataclass, field

import redis.asyncio as aioredis

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("emotionflow.live_worker")

SAMPLE_RATE = 16000
WINDOW_SECONDS = 3.0
OVERLAP_SECONDS = 0.5
MIN_RMS = 0.003
SESSION_TTL_SECONDS = 900


@dataclass
class LiveSession:
    session_id: str
    user_id: int
    tier: str = "fast"
    pcm: bytearray = field(default_factory=bytearray)
    offset_seconds: float = 0.0
    last_emitted_end: float = 0.0
    segments: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=lambda: {
        "asr_time_ms": 0.0,
        "emotion_time_ms": 0.0,
        "local_causality_time_ms": 0.0,
    })
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    buffer_started_at_ms: int | None = None
    received_samples: int = 0


async def publish(redis_client, session_id: str, payload: dict):
    await redis_client.publish(f"live:result:{session_id}", json.dumps(payload))


def _process_window(session: LiveSession, final: bool = False) -> dict | None:
    import numpy as np
    import soundfile as sf

    sample_count = len(session.pcm) // 2
    minimum = SAMPLE_RATE if final else int(WINDOW_SECONDS * SAMPLE_RATE)
    if sample_count < minimum:
        return None
    used_samples = sample_count if final else int(WINDOW_SECONDS * SAMPLE_RATE)
    raw = bytes(session.pcm[: used_samples * 2])
    waveform = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if float(np.sqrt(np.mean(np.square(waveform)))) < MIN_RMS:
        advance = used_samples if final else int((WINDOW_SECONDS - OVERLAP_SECONDS) * SAMPLE_RATE)
        del session.pcm[: advance * 2]
        session.offset_seconds += advance / SAMPLE_RATE
        return {"silent": True, "segments": [], "transitions": []}

    from app.services.asr_service import transcribe
    from app.services.multimodal_service import analyze_multimodal_segments, analyze_topics, build_transitions, stabilize_emotions

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        temp_path = tmp.name
    try:
        sf.write(temp_path, waveform, SAMPLE_RATE)
        asr_started = time.perf_counter()
        asr = transcribe(temp_path, tier="fast", language="en")
        asr_time_ms = (time.perf_counter() - asr_started) * 1000
        local_segments = [
            {**segment, "start": round(segment["start"] + session.offset_seconds, 2),
             "end": round(segment["end"] + session.offset_seconds, 2)}
            for segment in asr["segments"]
            if segment["end"] + session.offset_seconds > session.last_emitted_end + 0.1
        ]
        if not local_segments:
            analyzed = {"segments": [], "transitions": [], "overall_sentiment": "neutral", "summary": ""}
        else:
            # The analyzer needs local offsets for audio slicing, then timestamps are restored.
            analysis_input = [
                {**segment, "start": segment["start"] - session.offset_seconds,
                 "end": segment["end"] - session.offset_seconds}
                for segment in local_segments
            ]
            emotion_started = time.perf_counter()
            analyzed = analyze_multimodal_segments(
                analysis_input, temp_path, tier="fast", include_causality=False
            )
            emotion_time_ms = (time.perf_counter() - emotion_started) * 1000
            for result_segment, timestamped in zip(analyzed["segments"], local_segments):
                result_segment["start"], result_segment["end"] = timestamped["start"], timestamped["end"]

            if session.segments and analyzed["segments"]:
                previous = session.segments[-1].get("acoustic", {})
                current = analyzed["segments"][0].get("acoustic", {})
                current["energy_delta_db"] = round(current["rms_db"] - previous["rms_db"], 2)
                current["pitch_delta_hz"] = (
                    round(current["pitch_hz"] - previous["pitch_hz"], 1)
                    if current.get("pitch_hz") and previous.get("pitch_hz") else None
                )
                current["speech_rate_delta_wps"] = round(
                    current["speech_rate_wps"] - previous["speech_rate_wps"], 2
                )

            # Recompute rolling topics and cross-window stabilization using session context.
            all_text = [item["text"] for item in session.segments] + [item["text"] for item in analyzed["segments"]]
            rolling_topics = analyze_topics(all_text)
            for result_segment, topic in zip(analyzed["segments"], rolling_topics[-len(analyzed["segments"]):]):
                result_segment["topic"] = topic
            stabilize_emotions(
                analyzed["segments"],
                previous_label=session.segments[-1]["emotion"] if session.segments else None,
            )
            contextual = ([session.segments[-1]] if session.segments else []) + analyzed["segments"]
            causality_started = time.perf_counter()
            cross_transitions = build_transitions(contextual, use_model=False)
            causality_time_ms = (time.perf_counter() - causality_started) * 1000
            analyzed["transitions"] = [
                {**transition,
                 "from_segment": len(session.segments) + transition["from_segment"] - (1 if session.segments else 0),
                 "to_segment": len(session.segments) + transition["to_segment"] - (1 if session.segments else 0)}
                for transition in cross_transitions
            ]

        analyzed["stage_timings"] = {
            "asr_time_ms": round(asr_time_ms, 1),
            "emotion_time_ms": round(locals().get("emotion_time_ms", 0.0), 1),
            "local_causality_time_ms": round(locals().get("causality_time_ms", 0.0), 1),
        }

        advance = used_samples if final else int((WINDOW_SECONDS - OVERLAP_SECONDS) * SAMPLE_RATE)
        del session.pcm[: advance * 2]
        session.offset_seconds += advance / SAMPLE_RATE
        return analyzed
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


async def _emit_analysis(redis_client, session: LiveSession, analysis: dict, captured_at_ms: int):
    now_ms = int(time.time() * 1000)
    latency_ms = max(0, now_ms - captured_at_ms)
    outbound = []
    for key, value in analysis.get("stage_timings", {}).items():
        session.stage_timings[key] = round(session.stage_timings.get(key, 0.0) + float(value), 1)
    for segment in analysis.get("segments", []):
        session.last_emitted_end = max(session.last_emitted_end, segment["end"])
        session.segments.append(segment)
        transcript = {"start": segment["start"], "end": segment["end"], "text": segment["text"], "speaker": "Speaker 1"}
        session.transcript.append(transcript)
        outbound.append({"type": "transcript", "segment": transcript, "captured_at_ms": captured_at_ms})
        outbound.append({"type": "emotion", "segment": segment, "captured_at_ms": captured_at_ms})
    for transition in analysis.get("transitions", []):
        session.transitions.append(transition)
        outbound.append({"type": "causality", "transition": transition, "captured_at_ms": captured_at_ms})


    if outbound:
        pipeline = redis_client.pipeline(transaction=False)
        channel = f"live:result:{session.session_id}"
        for payload in outbound:
            pipeline.publish(channel, json.dumps(payload))
        await pipeline.execute()

def _warm_models():
    """Load and exercise live models before advertising this worker as ready.

    Loading a Transformers pipeline does not initialize every CUDA kernel.  A
    tiny inference here prevents the first real three-second window from
    paying that one-time cost and missing the five-second latency budget.
    """
    import numpy as np

    from app.services.asr_service import load_model
    from app.services.audio_emotion_service import AUDIO_MODEL_PRIMARY, load_audio_classifier
    from app.services.emotion_service import TIER_MODEL_MAP, load_classifier
    from app.services.local_causality_service import _load_qwen

    asr_model = load_model("fast")
    warm_waveform = (0.01 * np.sin(2 * np.pi * 220 * np.arange(SAMPLE_RATE) / SAMPLE_RATE)).astype(np.float32)
    warm_segments, _ = asr_model.transcribe(
        warm_waveform, language="en", beam_size=1, best_of=1,
        vad_filter=False, condition_on_previous_text=False, word_timestamps=False,
    )
    list(warm_segments)
    audio_classifier = load_audio_classifier(AUDIO_MODEL_PRIMARY)
    text_classifier = load_classifier(TIER_MODEL_MAP["fast"][0])
    text_classifier("Model warm-up sentence.")
    audio_classifier({"raw": np.zeros(SAMPLE_RATE, dtype=np.float32), "sampling_rate": SAMPLE_RATE})
    _load_qwen()


async def live_worker_loop():
    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    queue_key = f"live:worker:{worker_id}"
    heartbeat_key = f"live-worker:heartbeat:{worker_id}"
    gpu_resource = os.getenv("GPU_RESOURCE_ID", "default-gpu")
    live_priority_key = f"gpu:{gpu_resource}:live-priority"
    sessions: dict[str, LiveSession] = {}
    last_heartbeat = 0.0
    last_priority_refresh = 0.0
    logger.info("Warming resident live models before accepting sessions")
    await asyncio.to_thread(_warm_models)
    logger.info("Live GPU worker ready: %s", worker_id)

    while True:
        now_monotonic = time.monotonic()
        if now_monotonic - last_heartbeat >= 10.0:
            await redis_client.setex(heartbeat_key, 30, int(time.time()))
            last_heartbeat = now_monotonic
        item = await redis_client.blpop(queue_key, timeout=2)
        if not item:
            stale = [sid for sid, session in sessions.items() if time.time() - session.last_activity > SESSION_TTL_SECONDS]
            for sid in stale:
                sessions.pop(sid, None)
            if stale and not sessions:
                await redis_client.delete(live_priority_key)
            continue
        _, raw = item
        message = json.loads(raw)
        kind, session_id = message.get("type"), message.get("session_id")
        try:
            if kind == "start":
                sessions[session_id] = LiveSession(session_id=session_id, user_id=int(message["user_id"]), tier="fast")
                await redis_client.setex(live_priority_key, 30, worker_id)
                await publish(redis_client, session_id, {"type": "status", "message": "Capturing 3-second analysis window"})
            elif kind == "audio" and session_id in sessions:
                session = sessions[session_id]
                captured_at_ms = int(message.get("captured_at_ms", time.time() * 1000))
                chunk = base64.b64decode(message["data"])
                if not session.pcm:
                    chunk_ms = int((len(chunk) / 2 / SAMPLE_RATE) * 1000)
                    session.buffer_started_at_ms = captured_at_ms - chunk_ms
                session.pcm.extend(chunk)
                session.received_samples += len(chunk) // 2
                session.last_activity = time.time()
                if now_monotonic - last_priority_refresh >= 10.0:
                    await redis_client.setex(live_priority_key, 30, worker_id)
                    last_priority_refresh = now_monotonic
                if len(session.pcm) >= int(WINDOW_SECONDS * SAMPLE_RATE * 2):
                    analysis = await asyncio.to_thread(_process_window, session, False)
                    if analysis:
                        await _emit_analysis(
                            redis_client,
                            session,
                            analysis,
                            captured_at_ms - int(WINDOW_SECONDS * 1000),
                        )
                    session.buffer_started_at_ms = captured_at_ms - int(OVERLAP_SECONDS * 1000)
            elif kind == "end" and session_id in sessions:
                session = sessions[session_id]
                analysis = await asyncio.to_thread(_process_window, session, True)
                if analysis:
                    await _emit_analysis(
                        redis_client,
                        session,
                        analysis,
                        session.buffer_started_at_ms or int(time.time() * 1000),
                    )
                from app.services.local_causality_service import build_summary
                from app.services.multimodal_service import overall_sentiment
                summary_started = time.perf_counter()
                summary = build_summary(session.segments, session.transitions, use_model=True)
                session.stage_timings["local_causality_time_ms"] += round(
                    (time.perf_counter() - summary_started) * 1000, 1
                )
                result = {
                    "filename": "live-session.pcm",
                    "duration_seconds": round(session.received_samples / SAMPLE_RATE, 2),
                    "overall_sentiment": overall_sentiment(session.segments),
                    "summary": summary,
                    "timeline": [
                        {"timestamp_start": item["start"], "timestamp_end": item["end"], **item}
                        for item in session.segments
                    ],
                    "transcript": session.transcript, "transitions": session.transitions, "model_tier": "fast",
                    "processing_time_ms": int((time.time() - session.started_at) * 1000),
                    "stage_timings": session.stage_timings,
                    "model_provenance": {"asr": "faster-whisper/base.en", "audio_emotion": "superb/wav2vec2-base-superb-er",
                                         "text_emotion": "j-hartmann/emotion-english-distilroberta-base",
                                         "fusion": "weighted-audio-0.55-text-0.45",
                                         "causality": "Qwen/Qwen3-0.6B with deterministic fallback", "external_inference": False},
                }
                await publish(redis_client, session_id, {"type": "final_result", "result": result})
                sessions.pop(session_id, None)
                if not sessions:
                    await redis_client.delete(live_priority_key)
            elif kind == "cancel":
                sessions.pop(session_id, None)
                if not sessions:
                    await redis_client.delete(live_priority_key)
        except Exception as exc:
            logger.exception("Live session %s failed", session_id)
            await publish(redis_client, session_id, {"type": "error", "message": str(exc), "recoverable": True})


if __name__ == "__main__":
    asyncio.run(live_worker_loop())
