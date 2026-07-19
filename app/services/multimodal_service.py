"""Shared local multimodal analysis used by uploaded files and live streams."""
from __future__ import annotations

import math
import time
from collections import Counter

CANONICAL_EMOTIONS = ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")
LABEL_ALIASES = {
    "ang": "anger", "angry": "anger", "anger": "anger",
    "hap": "joy", "happy": "joy", "happiness": "joy", "joy": "joy",
    "neu": "neutral", "neutral": "neutral",
    "sad": "sadness", "sadness": "sadness",
    "fearful": "fear", "fear": "fear",
    "disgusted": "disgust", "disgust": "disgust",
    "surprised": "surprise", "surprise": "surprise",
}


def normalize_scores(scores: dict[str, float] | None) -> dict[str, float]:
    canonical = {emotion: 0.0 for emotion in CANONICAL_EMOTIONS}
    for label, score in (scores or {}).items():
        mapped = LABEL_ALIASES.get(label.lower())
        if mapped:
            canonical[mapped] += max(0.0, float(score))
    total = sum(canonical.values())
    if total <= 0:
        return {}
    return {label: round(score / total, 6) for label, score in canonical.items()}


def fuse_modalities(
    audio_scores: dict[str, float] | None,
    text_scores: dict[str, float] | None,
    audio_weight: float = 0.55,
    text_weight: float = 0.45,
) -> dict:
    audio = normalize_scores(audio_scores)
    text = normalize_scores(text_scores)
    if not audio and not text:
        scores = {"neutral": 1.0}
        audio_weight, text_weight = 0.0, 0.0
    elif not audio:
        scores, audio_weight, text_weight = text, 0.0, 1.0
    elif not text:
        scores, audio_weight, text_weight = audio, 1.0, 0.0
    else:
        scores = {
            emotion: audio_weight * audio.get(emotion, 0.0) + text_weight * text.get(emotion, 0.0)
            for emotion in CANONICAL_EMOTIONS
        }
        total = sum(scores.values()) or 1.0
        scores = {emotion: value / total for emotion, value in scores.items()}
    emotion = max(scores, key=scores.get)
    return {
        "emotion": emotion,
        "confidence": round(scores[emotion], 4),
        "scores": {key: round(value, 4) for key, value in scores.items()},
        "audio_weight": audio_weight,
        "text_weight": text_weight,
    }


def extract_acoustic_features(audio_path: str, start: float, end: float, text: str) -> dict:
    import librosa
    import numpy as np

    duration = max(0.01, end - start)
    try:
        waveform, sample_rate = librosa.load(
            audio_path, sr=16000, offset=start, duration=duration, mono=True
        )
    except Exception:
        return {
            "pitch_hz": None,
            "rms_db": -80.0,
            "speech_rate_wps": round(len(text.split()) / duration, 2),
            "duration_seconds": round(duration, 2),
        }
    if waveform.size == 0:
        return {"pitch_hz": None, "rms_db": -80.0, "speech_rate_wps": 0.0, "duration_seconds": duration}
    rms = float(np.sqrt(np.mean(np.square(waveform))))
    rms_db = 20 * math.log10(max(rms, 1e-8))
    pitches, magnitudes = librosa.piptrack(y=waveform, sr=sample_rate)
    voiced = pitches[magnitudes > np.percentile(magnitudes, 75)] if magnitudes.size else np.array([])
    pitch = float(np.median(voiced[voiced > 0])) if np.any(voiced > 0) else None
    return {
        "pitch_hz": round(pitch, 1) if pitch else None,
        "rms_db": round(rms_db, 2),
        "speech_rate_wps": round(len(text.split()) / duration, 2),
        "duration_seconds": round(duration, 2),
    }


def analyze_topics(texts: list[str]) -> list[dict]:
    if not texts:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=500)
        matrix = vectorizer.fit_transform(texts)
        features = vectorizer.get_feature_names_out()
        topics = []
        for index, row in enumerate(matrix):
            ranked = row.toarray()[0].argsort()[::-1]
            keywords = [features[i] for i in ranked if row[0, i] > 0][:3]
            similarity = 1.0 if index == 0 else float(cosine_similarity(matrix[index - 1], row)[0, 0])
            topics.append({
                "label": " / ".join(keywords[:2]) if keywords else "general conversation",
                "keywords": keywords,
                "similarity_to_previous": round(similarity, 4),
                "is_shift": index > 0 and similarity < 0.25 and len(texts[index].split()) >= 3,
            })
        return topics
    except (ValueError, ImportError):
        stop = {"the", "a", "an", "and", "or", "to", "of", "is", "it", "i", "you", "we", "this", "that"}
        topics = []
        previous: set[str] = set()
        for index, text in enumerate(texts):
            words = [word.strip(".,!?;:").lower() for word in text.split()]
            words = [word for word in words if len(word) > 2 and word not in stop]
            keywords = [word for word, _ in Counter(words).most_common(3)]
            current = set(keywords)
            union = previous | current
            similarity = len(previous & current) / len(union) if union and index else 1.0
            topics.append({"label": " / ".join(keywords[:2]) or "general conversation", "keywords": keywords,
                           "similarity_to_previous": round(similarity, 4),
                           "is_shift": index > 0 and similarity < 0.25 and len(words) >= 3})
            previous = current
        return topics


def stabilize_emotions(
    segments: list[dict], margin: float = 0.10, previous_label: str | None = None
) -> list[dict]:
    for segment in segments:
        scores = segment["modalities"]["fused"]["scores"]
        candidate = segment["modalities"]["fused"]["emotion"]
        if previous_label and candidate != previous_label:
            if scores.get(candidate, 0.0) - scores.get(previous_label, 0.0) < margin:
                candidate = previous_label
        segment["emotion"] = candidate
        segment["intensity"] = round(scores.get(candidate, 0.0), 4)
        previous_label = candidate
    return segments


def build_transitions(segments: list[dict], use_model: bool = True) -> list[dict]:
    from app.services.local_causality_service import (
        deterministic_cause,
        explain_transition,
        select_trigger_phrase,
    )

    transitions = []
    for index in range(1, len(segments)):
        previous, current = segments[index - 1], segments[index]
        current["trigger_phrase"] = None
        current["cause"] = None
        current["cause_source"] = None
        if previous["emotion"] == current["emotion"]:
            continue
        if use_model:
            cause, source = explain_transition(previous, current)
        else:
            cause = deterministic_cause(previous, current)
            source = "deterministic-fallback"
        trigger = select_trigger_phrase(current.get("text", ""))
        current.update({"trigger_phrase": trigger, "cause": cause, "cause_source": source})
        driver = "topic" if current.get("topic", {}).get("is_shift") else "tone"
        audio_emotion = current.get("modalities", {}).get("audio", {}).get("emotion")
        text_emotion = current.get("modalities", {}).get("text", {}).get("emotion")
        if audio_emotion and text_emotion and audio_emotion != text_emotion:
            driver = "mixed"
        transitions.append({
            "from_segment": index - 1, "to_segment": index,
            "from_emotion": previous["emotion"], "to_emotion": current["emotion"],
            "explanation": cause, "driver": driver,
        })
    return transitions


def overall_sentiment(segments: list[dict]) -> str:
    valence = {"joy": 1, "surprise": 0.2, "neutral": 0, "fear": -1, "sadness": -1, "anger": -1, "disgust": -1}
    if not segments:
        return "neutral"
    values = [valence.get(segment["emotion"], 0) * segment["intensity"] for segment in segments]
    mean = sum(values) / len(values)
    if mean > 0.2:
        return "positive"
    if mean < -0.2:
        return "negative"
    return "mixed" if any(value > 0.2 for value in values) and any(value < -0.2 for value in values) else "neutral"


def analyze_multimodal_segments(
    segments: list[dict],
    audio_path: str,
    tier: str = "fast",
    include_causality: bool = True,
) -> dict:
    from app.services.audio_emotion_service import classify_audio_segment
    from app.services.emotion_service import classify_segment
    from app.services.local_causality_service import build_summary

    started = time.perf_counter()
    topics = analyze_topics([segment.get("text", "") for segment in segments])
    analyzed: list[dict] = []
    previous_acoustic = None
    for index, segment in enumerate(segments):
        acoustic = extract_acoustic_features(audio_path, segment["start"], segment["end"], segment["text"])
        text_result = classify_segment(segment["text"], tier) if segment["text"].strip() else {
            "primary_emotion": "neutral", "primary_score": 0.0, "all_emotions": {}, "model": "missing-text"
        }
        audio_result = (
            classify_audio_segment(audio_path, segment["start"], segment["end"], tier)
            if acoustic["rms_db"] > -60.0
            else {"primary_emotion": "neutral", "primary_score": 0.0, "all_emotions": {}, "model": "silent-audio"}
        )
        acoustic["energy_delta_db"] = (
            round(acoustic["rms_db"] - previous_acoustic["rms_db"], 2) if previous_acoustic else None
        )
        acoustic["pitch_delta_hz"] = (
            round(acoustic["pitch_hz"] - previous_acoustic["pitch_hz"], 1)
            if previous_acoustic and acoustic["pitch_hz"] and previous_acoustic["pitch_hz"] else None
        )
        acoustic["speech_rate_delta_wps"] = (
            round(acoustic["speech_rate_wps"] - previous_acoustic["speech_rate_wps"], 2)
            if previous_acoustic else None
        )
        previous_acoustic = acoustic
        audio_scores = {} if audio_result.get("model") in {"fallback", "silent-audio"} else audio_result.get("all_emotions")
        fused = fuse_modalities(audio_scores, text_result.get("all_emotions"))
        analyzed.append({
            "start": segment["start"], "end": segment["end"], "text": segment["text"],
            "emotion": fused["emotion"], "intensity": fused["confidence"],
            "modalities": {
                "audio": {"emotion": LABEL_ALIASES.get(audio_result["primary_emotion"], audio_result["primary_emotion"]),
                          "confidence": audio_result["primary_score"], "scores": normalize_scores(audio_result["all_emotions"])},
                "text": {"emotion": LABEL_ALIASES.get(text_result["primary_emotion"], text_result["primary_emotion"]),
                         "confidence": text_result["primary_score"], "scores": normalize_scores(text_result["all_emotions"])},
                "fused": fused,
            },
            "topic": topics[index], "acoustic": acoustic,
            "trigger_phrase": None, "cause": None, "cause_source": None,
        })
    stabilize_emotions(analyzed)
    causality_started = time.perf_counter()
    transitions = build_transitions(analyzed) if include_causality else []
    causality_time_ms = (time.perf_counter() - causality_started) * 1000
    return {
        "segments": analyzed,
        "transitions": transitions,
        "overall_sentiment": overall_sentiment(analyzed),
        "summary": build_summary(analyzed, transitions, use_model=False),
        "stage_timings": {"local_causality_time_ms": round(causality_time_ms, 1)},
        "processing_time_ms": round((time.perf_counter() - started) * 1000, 1),
    }
