#!/usr/bin/env python3
"""Run real offline models on the local machine and save evaluation evidence."""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AUDIO = ROOT / "test_data" / "demo_speech.wav"
OUTPUT = ROOT / "docs" / "evidence" / "local-runtime-result.json"

os.environ["LOCAL_MODELS_ONLY"] = "true"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def main():
    import numpy as np
    import soundfile as sf
    import torch

    from app.services.asr_service import transcribe, unload_model
    from app.services.live_worker import LiveSession, _process_window
    from app.services.worker import process_audio_file

    report: dict = {
        "generated_at_epoch": time.time(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cuda": torch.version.cuda,
        "tests": {},
    }

    # Exercise each proposal tier with its real ASR model while keeping VRAM bounded.
    for tier in ("fast", "balanced", "max"):
        started = time.perf_counter()
        result = transcribe(str(AUDIO), tier=tier, language="en")
        report["tests"][f"asr_{tier}"] = {
            "passed": True,
            "model": result["model"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "segments": len(result["segments"]),
            "text": result["text"],
        }
        unload_model(tier)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    started = time.perf_counter()
    file_result = process_audio_file(
        file_path=str(AUDIO), model_tier="fast", user_id=0, session_id="local-runtime"
    )
    file_result["processing_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
    assert file_result["model_provenance"]["external_inference"] is False
    assert "timeline" in file_result and "transitions" in file_result
    report["tests"]["file_pipeline"] = {"passed": True, "result": file_result}

    waveform, sample_rate = sf.read(AUDIO, dtype="float32", always_2d=False)
    if sample_rate != 16000:
        import librosa

        waveform = librosa.resample(np.asarray(waveform), orig_sr=sample_rate, target_sr=16000)
    pcm = (np.clip(waveform, -1, 1) * 32767).astype("<i2").tobytes()
    live_session = LiveSession(session_id="local-live", user_id=0)
    live_session.pcm.extend(pcm[: 3 * 16000 * 2])
    started = time.perf_counter()
    live_result = _process_window(live_session, final=False)
    live_elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    assert live_result is not None
    report["tests"]["live_window"] = {
        "passed": True,
        "elapsed_ms": live_elapsed_ms,
        "within_five_seconds": live_elapsed_ms <= 5000,
        "result": live_result,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "gpu": report["gpu"],
        "asr": {key: value["elapsed_ms"] for key, value in report["tests"].items() if key.startswith("asr_")},
        "file_ms": file_result["processing_time_ms"],
        "live_ms": live_elapsed_ms,
        "live_under_5s": live_elapsed_ms <= 5000,
    }, indent=2))


if __name__ == "__main__":
    main()
