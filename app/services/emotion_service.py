"""
Emotion Classification Service — Transformer-based emotion detection on text segments.

Tiers:
  fast:      6 emotions
  balanced:  28 emotions
  max:       ensemble of both
"""
import logging
import time

import torch
from transformers import pipeline, Pipeline

logger = logging.getLogger("emotionflow.emotion")

TIER_MODEL_MAP = {
    "fast": ["j-hartmann/emotion-english-distilroberta-base"],
    "balanced": ["j-hartmann/emotion-english-distilroberta-base"],
    "max": ["j-hartmann/emotion-english-distilroberta-base"],
}

# Module-level cache
_pipelines: dict[str, Pipeline] = {}


def _get_device() -> int:
    """Return device index for transformers pipeline."""
    return 0 if torch.cuda.is_available() else -1


def load_classifier(model_name: str) -> Pipeline:
    """Load and cache a text-classification pipeline."""
    if model_name in _pipelines:
        return _pipelines[model_name]

    device = _get_device()
    logger.info(f"Loading emotion classifier '{model_name}' on device={device}...")
    t0 = time.perf_counter()

    pipe = pipeline(
        "text-classification",
        model=model_name,
        top_k=None,  # Return all labels with scores
        device=device,
        truncation=True,
        max_length=512,
        local_files_only=True,
    )

    elapsed = time.perf_counter() - t0
    logger.info(f"Classifier '{model_name}' loaded in {elapsed:.1f}s")

    _pipelines[model_name] = pipe
    return pipe


def classify_segment(text: str, tier: str = "balanced") -> dict:
    """
    Classify emotion for a single text segment.

    Returns:
        {
            "primary_emotion": str,
            "primary_score": float,
            "all_emotions": {emotion: score, ...},
            "model": str,
        }
    """
    model_names = TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["balanced"])

    if len(model_names) > 1:
        return _ensemble_classify(text, model_names)

    model_name = model_names[0]
    pipe = load_classifier(model_name)

    results = pipe(text)
    # pipeline with top_k=None returns List[List[dict]] for single input
    if results and isinstance(results[0], list):
        results = results[0]

    all_emotions = {r["label"]: round(r["score"], 4) for r in results}
    primary = max(results, key=lambda x: x["score"])

    return {
        "primary_emotion": primary["label"],
        "primary_score": round(primary["score"], 4),
        "all_emotions": all_emotions,
        "model": model_name,
    }


def _ensemble_classify(text: str, model_names: list[str]) -> dict:
    """
    Average scores across multiple models.
    Maps disparate label sets to a common set by keeping all labels
    and averaging where both models have the same label.
    """
    combined: dict[str, list[float]] = {}

    for model_name in model_names:
        pipe = load_classifier(model_name)
        results = pipe(text)
        if results and isinstance(results[0], list):
            results = results[0]

        for r in results:
            label = r["label"]
            if label not in combined:
                combined[label] = []
            combined[label].append(r["score"])

    # Average scores
    all_emotions = {
        label: round(sum(scores) / len(scores), 4)
        for label, scores in combined.items()
    }

    primary_label = max(all_emotions, key=all_emotions.get)

    return {
        "primary_emotion": primary_label,
        "primary_score": all_emotions[primary_label],
        "all_emotions": all_emotions,
        "model": "ensemble",
    }


def classify_segments(
    segments: list[dict],
    tier: str = "balanced",
) -> list[dict]:
    """
    Classify emotions for a list of transcript segments.

    Args:
        segments: List of {"start": float, "end": float, "text": str}
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
    # Batch-load the models up front
    model_names = TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["balanced"])
    for name in model_names:
        load_classifier(name)

    results = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        classification = classify_segment(text, tier)

        results.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
            "emotion": classification["primary_emotion"],
            "intensity": classification["primary_score"],
            "all_emotions": classification["all_emotions"],
        })

    return results


def unload_classifiers():
    """Free GPU memory by clearing all cached classifiers."""
    _pipelines.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("Unloaded all emotion classifiers")
