"""Manual offline smoke test for the complete local file pipeline."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def require_fixture() -> str:
    path = "test_data/test_audio.wav"
    if not os.path.exists(path):
        raise SystemExit(f"Missing fixture: {path}")
    return path


def test_local_services(audio_path: str):
    from app.services.asr_service import transcribe
    from app.services.multimodal_service import analyze_multimodal_segments

    started = time.perf_counter()
    asr = transcribe(audio_path, tier="fast", language="en")
    analysis = analyze_multimodal_segments(asr["segments"], audio_path, tier="fast")
    elapsed = time.perf_counter() - started

    assert analysis["overall_sentiment"]
    for segment in analysis["segments"]:
        assert segment["emotion"]
        assert segment["modalities"]
        assert segment["topic"]
        assert segment["acoustic"]
        if segment.get("trigger_phrase"):
            assert segment["trigger_phrase"] in segment["text"]
    print(f"Local services: {len(analysis['segments'])} segments in {elapsed:.2f}s")


def test_full_worker(audio_path: str):
    import redis

    from app.core.config import get_settings
    from app.services.worker import process_audio_file

    settings = get_settings()
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    started = time.perf_counter()
    result = process_audio_file(
        file_path=audio_path,
        model_tier="fast",
        user_id=0,
        session_id="offline-smoke",
        redis_client=client,
    )
    assert result["model_provenance"]["external_inference"] is False
    assert "timeline" in result and "transitions" in result
    print(f"Full worker: {len(result['timeline'])} segments in {time.perf_counter() - started:.2f}s")


if __name__ == "__main__":
    os.environ.setdefault("LOCAL_MODELS_ONLY", "true")
    fixture = require_fixture()
    test_local_services(fixture)
    test_full_worker(fixture)
    print("OFFLINE LOCAL PIPELINE PASSED")
