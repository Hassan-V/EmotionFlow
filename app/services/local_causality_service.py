"""Grounded, fully local causal explanations with a deterministic fallback."""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger("emotionflow.local_causality")

MODEL_NAME = os.getenv("LOCAL_CAUSAL_MODEL", "Qwen/Qwen3-0.6B")
MAX_NEW_TOKENS = int(os.getenv("LOCAL_CAUSAL_MAX_NEW_TOKENS", "72"))
GENERATION_TIMEOUT_SECONDS = float(os.getenv("LOCAL_CAUSAL_TIMEOUT_SECONDS", "4.0"))

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-causality")
_tokenizer = None
_model = None


def select_trigger_phrase(text: str) -> str | None:
    """Choose a short exact clause; the returned value is always a transcript substring."""
    text = (text or "").strip()
    if not text:
        return None
    clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+|[,;:]\s*", text) if part.strip()]
    emotional = ("not", "never", "why", "problem", "sorry", "thank", "love", "hate", "can't", "won't")
    selected = next((part for part in clauses if any(cue in part.lower() for cue in emotional)), clauses[0])
    return selected[:180].strip()


def deterministic_cause(previous: dict | None, current: dict) -> str:
    """Build an auditable explanation from measured topic, modality, and acoustic changes."""
    parts: list[str] = []
    topic = current.get("topic", {})
    acoustic = current.get("acoustic", {})
    modalities = current.get("modalities", {})

    if previous:
        parts.append(f"The emotion changes from {previous['emotion']} to {current['emotion']}")
    else:
        parts.append(f"The detected emotion is {current['emotion']}")
    if topic.get("is_shift"):
        old_topic = (previous or {}).get("topic", {}).get("label", "the earlier subject")
        parts.append(f"as the topic moves from {old_topic} to {topic.get('label', 'a new subject')}")
    audio = modalities.get("audio", {})
    text = modalities.get("text", {})
    if audio.get("emotion") == text.get("emotion") and audio.get("emotion"):
        parts.append("with matching vocal and textual evidence")
    else:
        parts.append("with the fused result resolving different vocal and textual signals")
    if acoustic.get("energy_delta_db") is not None and abs(acoustic["energy_delta_db"]) >= 3:
        direction = "rising" if acoustic["energy_delta_db"] > 0 else "falling"
        parts.append(f"and {direction} vocal energy")
    if acoustic.get("pitch_delta_hz") is not None and abs(acoustic["pitch_delta_hz"]) >= 20:
        direction = "higher" if acoustic["pitch_delta_hz"] > 0 else "lower"
        parts.append(f"with {direction} pitch")
    if acoustic.get("speech_rate_delta_wps") is not None and abs(acoustic["speech_rate_delta_wps"]) >= 0.5:
        direction = "faster" if acoustic["speech_rate_delta_wps"] > 0 else "slower"
        parts.append(f"and {direction} speech")
    return ", ".join(parts) + "."


def _load_qwen():
    global _tokenizer, _model
    if _tokenizer is not None and _model is not None:
        return _tokenizer, _model
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=True)
    if torch.cuda.is_available():
        major_capability, _ = torch.cuda.get_device_capability()
        dtype = (
            torch.bfloat16
            if major_capability >= 8 and torch.cuda.is_bf16_supported()
            else torch.float16
        )
    else:
        dtype = torch.float32
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        local_files_only=True,
    )
    return _tokenizer, _model


def _generate(evidence: str) -> str:
    tokenizer, model = _load_qwen()
    messages = [
        {
            "role": "system",
            "content": (
                "Explain an observed emotion shift in one clinical sentence. Use only the supplied "
                "evidence, do not claim proof, do not change labels, and return plain text only. /no_think"
            ),
        },
        {"role": "user", "content": evidence},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    output = model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
    )
    text = tokenizer.decode(output[0][inputs.input_ids.shape[-1]:], skip_special_tokens=True).strip()
    return text.splitlines()[0][:500]


def _generate_summary(evidence: str) -> str:
    tokenizer, model = _load_qwen()
    messages = [
        {
            "role": "system",
            "content": (
                "Phrase the supplied measured emotional timeline as two concise sentences. "
                "Do not add facts or alter labels, counts, or confidence. /no_think"
            ),
        },
        {"role": "user", "content": evidence},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    output = model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
    )
    return tokenizer.decode(
        output[0][inputs.input_ids.shape[-1]:], skip_special_tokens=True
    ).strip()[:700]


def explain_transition(previous: dict | None, current: dict) -> tuple[str, str]:
    fallback = deterministic_cause(previous, current)
    evidence = fallback + f" Transcript trigger: {select_trigger_phrase(current.get('text', '')) or 'none'}."
    future = _executor.submit(_generate, evidence)
    try:
        generated = future.result(timeout=GENERATION_TIMEOUT_SECONDS)
        if generated and len(generated) >= 20:
            return generated, MODEL_NAME.rsplit("/", 1)[-1].lower()
    except (TimeoutError, Exception) as exc:
        future.cancel()
        logger.warning("Local causal generation unavailable; using grounded fallback: %s", exc)
    return fallback, "deterministic-fallback"


def build_summary(segments: list[dict], transitions: list[dict], use_model: bool = True) -> str:
    if not segments:
        return "No speech was detected."
    emotions = [segment["emotion"] for segment in segments]
    dominant = max(set(emotions), key=emotions.count)
    fallback = (
        f"The conversation is predominantly {dominant}. "
        f"{len(transitions)} stabilized emotion shift{'s were' if len(transitions) != 1 else ' was'} detected "
        "from fused vocal and textual evidence."
    )
    if not use_model:
        return fallback
    evidence = (
        f"Dominant emotion: {dominant}. Stabilized sequence: {' -> '.join(emotions)}. "
        f"Transition count: {len(transitions)}."
    )
    future = _executor.submit(_generate_summary, evidence)
    try:
        generated = future.result(timeout=GENERATION_TIMEOUT_SECONDS)
        if generated and len(generated) >= 30:
            return generated
    except (TimeoutError, Exception) as exc:
        future.cancel()
        logger.warning("Local summary generation unavailable; using deterministic fallback: %s", exc)
    return fallback


def build_session_summary(segments: list[dict], result: dict) -> str:
    return result.get("summary") or build_summary(segments, result.get("transitions", []))
