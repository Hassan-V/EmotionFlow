"""
ASR Service — Whisper-based speech-to-text with multi-tier model support.
"""
import logging
import time
from typing import Optional

import torch
import whisper

logger = logging.getLogger("emotionflow.asr")

TIER_MODEL_MAP = {
    "fast":     "small",
    "balanced": "medium",
    "max":      "large-v3",
}

# Module-level cache: loaded models
_loaded_models: dict[str, whisper.Whisper] = {}


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_model(tier: str) -> whisper.Whisper:
    """Load and cache the model for the given tier."""
    model_name = TIER_MODEL_MAP.get(tier, "small")

    if model_name in _loaded_models:
        return _loaded_models[model_name]

    device = _get_device()
    logger.info(f"Loading Whisper '{model_name}' on {device}...")
    t0 = time.perf_counter()

    model = whisper.load_model(model_name, device=device)

    elapsed = time.perf_counter() - t0
    logger.info(f"Whisper '{model_name}' loaded in {elapsed:.1f}s")

    _loaded_models[model_name] = model
    return model


def transcribe(file_path: str, tier: str = "balanced", language: Optional[str] = None) -> dict:
    """
    Transcribe an audio file using Whisper.

    Returns:
        {
            "text": str,            # Full transcript
            "language": str,        # Detected language
            "segments": [           # Time-aligned segments
                {
                    "start": float,
                    "end": float,
                    "text": str,
                }
            ],
            "duration_seconds": float,
        }
    """
    model = load_model(tier)

    logger.info(f"Transcribing '{file_path}' with tier={tier}")

    # Validate file exists and is readable before passing to Whisper
    import os
    import subprocess
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")
    logger.info(f"File size: {os.path.getsize(file_path)} bytes")

    # Pre-check ffmpeg can read the file
    try:
        probe = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", file_path, "-f", "null", "-"],
            capture_output=True, timeout=30,
        )
        if probe.returncode != 0:
            logger.error(f"ffmpeg probe failed (rc={probe.returncode}): {probe.stderr.decode()[:500]}")
    except Exception as fe:
        logger.error(f"ffmpeg probe exception: {fe}")

    t0 = time.perf_counter()

    options = {
        "fp16": torch.cuda.is_available(),
        "verbose": False,
    }
    if language:
        options["language"] = language

    result = whisper.transcribe(model, file_path, **options)

    elapsed = time.perf_counter() - t0
    logger.info(f"Transcription done in {elapsed:.1f}s ({len(result['segments'])} segments)")

    # Extract duration from last segment or audio
    duration = 0.0
    if result["segments"]:
        duration = result["segments"][-1]["end"]

    segments = [
        {
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
        }
        for seg in result["segments"]
        if seg["text"].strip()
    ]

    return {
        "text": result["text"].strip(),
        "language": result.get("language", "en"),
        "segments": segments,
        "duration_seconds": round(duration, 2),
    }


def unload_model(tier: Optional[str] = None):
    """Free GPU memory by unloading models."""
    if tier:
        model_name = TIER_MODEL_MAP.get(tier, tier)
        if model_name in _loaded_models:
            del _loaded_models[model_name]
            logger.info(f"Unloaded Whisper '{model_name}'")
    else:
        _loaded_models.clear()
        logger.info("Unloaded all Whisper models")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
