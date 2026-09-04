"""Local Faster-Whisper ASR with models kept resident per worker."""
import logging
import os
import time
from typing import Optional, Union

logger = logging.getLogger("emotionflow.asr")

TIER_MODEL_MAP = {
    "fast": "base.en",
    "balanced": "small.en",
    "max": "medium.en",
}

_loaded_models: dict[str, object] = {}


def _device_config() -> tuple[str, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "int8_float16"
    except ImportError:
        pass
    return "cpu", "int8"


def load_model(tier: str):
    """Load and cache one CTranslate2 Whisper model."""
    from faster_whisper import WhisperModel

    model_name = TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["fast"])
    if model_name in _loaded_models:
        return _loaded_models[model_name]

    device, compute_type = _device_config()
    logger.info("Loading Faster-Whisper '%s' on %s (%s)", model_name, device, compute_type)
    started = time.perf_counter()
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        local_files_only=os.getenv("LOCAL_MODELS_ONLY", "true").lower() == "true",
    )
    _loaded_models[model_name] = model
    logger.info("Loaded Faster-Whisper '%s' in %.1fs", model_name, time.perf_counter() - started)
    return model


def transcribe(
    audio: Union[str, object],
    tier: str = "balanced",
    language: Optional[str] = "en",
) -> dict:
    """Transcribe a file path or float32 waveform and return timestamped segments."""
    if isinstance(audio, str) and not os.path.exists(audio):
        raise FileNotFoundError(f"Audio file not found: {audio}")

    model = load_model(tier)
    started = time.perf_counter()
    generated, info = model.transcribe(
        audio,
        language=language,
        beam_size=1,
        best_of=1,
        vad_filter=True,
        condition_on_previous_text=False,
        word_timestamps=False,
    )
    raw_segments = list(generated)
    segments = [
        {
            "start": round(float(segment.start), 2),
            "end": round(float(segment.end), 2),
            "text": segment.text.strip(),
        }
        for segment in raw_segments
        if segment.text.strip()
    ]
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    if duration <= 0:
        duration = max((segment["end"] for segment in segments), default=0.0)
    text = " ".join(segment["text"] for segment in segments).strip()
    logger.info("ASR produced %d segments in %.0fms", len(segments), (time.perf_counter() - started) * 1000)
    return {
        "text": text,
        "language": getattr(info, "language", language or "en"),
        "segments": segments,
        "duration_seconds": round(duration, 2),
        "model": TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["fast"]),
    }


def unload_model(tier: Optional[str] = None):
    """Compatibility hook; live workers intentionally keep models resident."""
    if tier:
        _loaded_models.pop(TIER_MODEL_MAP.get(tier, tier), None)
    else:
        _loaded_models.clear()
