"""
Audio-based Speech Emotion Recognition (SER) Service.

Detects emotion directly from the audio waveform — capturing tone, pitch,
prosody, and vocal quality that text-only classifiers miss.

Labels: ang (angry), hap (happy), neu (neutral), sad
"""
import logging
import time

import numpy as np
import torch
import torchaudio
from transformers import (
    Pipeline,
    pipeline,
)

logger = logging.getLogger("emotionflow.audio_emotion")

# ─── Model configuration ────────────────────────────────────────────────────

AUDIO_MODEL_PRIMARY = "superb/wav2vec2-base-superb-er"
AUDIO_MODEL_XLSR   = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
AUDIO_MODEL_HUBERT = "superb/hubert-large-superb-er"

TIER_MODEL_MAP = {
    "fast":     [AUDIO_MODEL_PRIMARY],
    "balanced": [AUDIO_MODEL_PRIMARY, AUDIO_MODEL_XLSR],
    "max":      [AUDIO_MODEL_PRIMARY, AUDIO_MODEL_XLSR, AUDIO_MODEL_HUBERT],
}

# Label mapping: abbreviated labels → full names
LABEL_NORMALIZE = {
    "ang": "angry",
    "hap": "happy",
    "neu": "neutral",
    "sad": "sad",
    # full labels (in case model config differs)
    "angry": "angry",
    "happy": "happy",
    "neutral": "neutral",
}

TARGET_SR = 16000

# ─── Module-level cache ─────────────────────────────────────────────────────

_pipelines: dict[str, Pipeline] = {}


def _get_device() -> int:
    return 0 if torch.cuda.is_available() else -1


def load_audio_classifier(model_name: str) -> Pipeline:
    """Load and cache an audio-classification pipeline."""
    if model_name in _pipelines:
        return _pipelines[model_name]

    device = _get_device()
    logger.info(f"Loading audio SER model '{model_name}' on device={device}...")
    t0 = time.perf_counter()

    pipe = pipeline(
        "audio-classification",
        model=model_name,
        device=device,
    )

    elapsed = time.perf_counter() - t0
    logger.info(f"Audio SER model '{model_name}' loaded in {elapsed:.1f}s")

    _pipelines[model_name] = pipe
    return pipe


def _load_audio_segment(
    audio_path: str,
    start_sec: float,
    end_sec: float,
) -> np.ndarray:
    """
    Load a segment of audio from file.
    Returns 1D float32 numpy array at 16kHz.
    """
    import soundfile as sf
    info = sf.info(audio_path)
    sr = info.samplerate

    frame_start = int(start_sec * sr)
    num_frames = int((end_sec - start_sec) * sr)

    waveform, file_sr = torchaudio.load(
        audio_path,
        frame_offset=frame_start,
        num_frames=num_frames,
    )

    # Mix to mono if stereo
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Resample to 16kHz if needed
    if file_sr != TARGET_SR:
        resampler = torchaudio.transforms.Resample(file_sr, TARGET_SR)
        waveform = resampler(waveform)

    return waveform.squeeze(0).numpy().astype(np.float32)


def classify_audio_segment(
    audio_path: str,
    start_sec: float,
    end_sec: float,
    tier: str = "balanced",
) -> dict:
    """
    Classify emotion from an audio segment.

    Returns:
        {
            "primary_emotion": str,
            "primary_score": float,
            "all_emotions": {emotion: score, ...},
            "model": str,
        }
    """
    model_names = TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["balanced"])

    # Load audio segment once
    try:
        audio_array = _load_audio_segment(audio_path, start_sec, end_sec)
    except Exception as e:
        logger.error(f"Failed to load audio segment [{start_sec:.1f}-{end_sec:.1f}s] from {audio_path}: {e}")
        return {
            "primary_emotion": "neutral",
            "primary_score": 0.5,
            "all_emotions": {"neutral": 0.5},
            "model": "fallback",
        }

    # Check minimum audio length (~0.5s at 16kHz)
    if len(audio_array) < 8000:
        logger.warning(f"Audio segment too short ({len(audio_array)} samples), padding")
        audio_array = np.pad(audio_array, (0, 8000 - len(audio_array)))

    if len(model_names) > 1:
        return _ensemble_classify_audio(audio_array, model_names)

    model_name = model_names[0]
    pipe = load_audio_classifier(model_name)

    results = pipe({"raw": audio_array, "sampling_rate": TARGET_SR})

    # Normalize labels
    all_emotions: dict[str, float] = {}
    for r in results:
        label = LABEL_NORMALIZE.get(r["label"].lower(), r["label"].lower())
        all_emotions[label] = round(r["score"], 4)

    primary_label = max(all_emotions, key=all_emotions.get)  # type: ignore[arg-type]

    return {
        "primary_emotion": primary_label,
        "primary_score": all_emotions[primary_label],
        "all_emotions": all_emotions,
        "model": model_name,
    }


def _ensemble_classify_audio(
    audio_array: np.ndarray,
    model_names: list[str],
) -> dict:
    """Ensemble multiple audio SER models — average normalized scores."""
    combined: dict[str, list[float]] = {}

    for model_name in model_names:
        pipe = load_audio_classifier(model_name)
        results = pipe({"raw": audio_array, "sampling_rate": TARGET_SR})

        for r in results:
            label = LABEL_NORMALIZE.get(r["label"].lower(), r["label"].lower())
            if label not in combined:
                combined[label] = []
            combined[label].append(r["score"])

    all_emotions = {
        label: round(sum(scores) / len(scores), 4)
        for label, scores in combined.items()
    }

    primary_label = max(all_emotions, key=all_emotions.get)  # type: ignore[arg-type]

    return {
        "primary_emotion": primary_label,
        "primary_score": all_emotions[primary_label],
        "all_emotions": all_emotions,
        "model": "ensemble",
    }


def classify_segments_audio(
    segments: list[dict],
    audio_path: str,
    tier: str = "balanced",
) -> list[dict]:
    """
    Classify emotions for all transcript segments using the audio waveform.

    Args:
        segments: List of {"start": float, "end": float, "text": str}
        audio_path: Path to the source audio file
        tier: Model tier

    Returns:
        List of:
        {
            "start": float,
            "end": float,
            "text": str,
            "emotion": str,
            "intensity": float,
            "all_emotions": {emotion: score, ...},
        }
    """
    # Pre-load models
    model_names = TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["balanced"])
    for name in model_names:
        load_audio_classifier(name)

    results = []
    for seg in segments:
        start = seg["start"]
        end = seg["end"]
        text = seg.get("text", "").strip()

        if not text:
            continue

        classification = classify_audio_segment(audio_path, start, end, tier)

        results.append({
            "start": start,
            "end": end,
            "text": text,
            "emotion": classification["primary_emotion"],
            "intensity": classification["primary_score"],
            "all_emotions": classification["all_emotions"],
        })

    return results


def unload_audio_classifiers():
    """Free GPU memory by clearing all cached audio classifiers."""
    _pipelines.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("Unloaded all audio SER classifiers")
