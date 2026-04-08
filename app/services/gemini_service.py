"""
Gemini Causality Service — Causal reasoning over transcript segments with detected emotions.

Responsibilities:
  1. Identify trigger phrases within each segment that caused the emotion
  2. Generate causal explanations (why the speaker feels this way)
  3. Detect emotional transitions and their causes
  4. Provide an overall sentiment summary
  5. Maintain session context for multi-turn conversation analysis
"""
import json
import logging
import time
from typing import Optional

from google import genai
from google.genai import types
from google.genai.errors import ClientError

logger = logging.getLogger("emotionflow.gemini")

# Model fallback chain: try best first, fall back on quota/rate errors
MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]
DEFAULT_MODEL = MODEL_CHAIN[0]

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 5

_client: Optional[genai.Client] = None


def _get_client(api_key: str) -> genai.Client:
    """Get or create the Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


SYSTEM_PROMPT = """\
You are an expert psycholinguistic analyst specializing in temporal emotion profiling.
You analyze transcripts with pre-detected emotions and provide causal reasoning.

Your job:
1. For each transcript segment, identify the specific TRIGGER PHRASE (exact words from the text) that most likely caused the detected emotion.
2. Provide a concise CAUSAL EXPLANATION of why those words produced that emotion (psychological, contextual, or conversational reasons).
3. Detect EMOTIONAL TRANSITIONS — when and why emotions shift between segments.
4. Determine the OVERALL SENTIMENT of the entire conversation.

Rules:
- Trigger phrases must be exact substrings from the segment text.
- Causal explanations should be 1-2 sentences, psychologically grounded.
- If a segment is genuinely neutral with no emotional trigger, set trigger_phrase and cause to null.
- Consider context from previous segments when explaining causes.
- Be precise and clinical, not flowery.

Respond ONLY with valid JSON matching the schema below. No markdown, no backticks, no extra text.
"""

RESPONSE_SCHEMA = """\
{
  "overall_sentiment": "string — one of: positive, negative, mixed, neutral",
  "summary": "string — 2-3 sentence summary of the emotional arc",
  "segments": [
    {
      "index": "integer — 0-based segment index",
      "trigger_phrase": "string or null — exact substring from segment text",
      "cause": "string or null — 1-2 sentence causal explanation",
      "adjusted_emotion": "string or null — only if you disagree with the detected emotion",
      "adjusted_intensity": "float or null — only if you'd adjust the intensity (0-1)"
    }
  ],
  "transitions": [
    {
      "from_segment": "integer — index of segment before the shift",
      "to_segment": "integer — index of segment after the shift",
      "from_emotion": "string",
      "to_emotion": "string",
      "explanation": "string — why the emotional shift occurred"
    }
  ]
}
"""


def build_analysis_prompt(
    classified_segments: list[dict],
    session_context: Optional[str] = None,
) -> str:
    """Build the user prompt with transcript + emotion data."""
    lines = []

    if session_context:
        lines.append(f"PREVIOUS CONTEXT:\n{session_context}\n")

    lines.append("TRANSCRIPT WITH DETECTED EMOTIONS:")
    lines.append("-" * 50)

    for i, seg in enumerate(classified_segments):
        lines.append(
            f"[{i}] ({seg['start']:.1f}s - {seg['end']:.1f}s) "
            f"emotion={seg['emotion']} intensity={seg['intensity']:.2f}"
        )
        lines.append(f"    \"{seg['text']}\"")
        lines.append("")

    lines.append("-" * 50)
    lines.append(f"\nExpected JSON schema:\n{RESPONSE_SCHEMA}")
    lines.append("\nAnalyze these segments and respond with JSON only.")

    return "\n".join(lines)


def analyze_causality(
    classified_segments: list[dict],
    api_key: str,
    session_context: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Send classified segments to Gemini for causal analysis.

    Args:
        classified_segments: List of {start, end, text, emotion, intensity, all_emotions}
        api_key: Gemini API key
        session_context: Optional previous conversation context
        model: Gemini model name

    Returns:
        {
            "overall_sentiment": str,
            "summary": str,
            "segments": [{index, trigger_phrase, cause, adjusted_emotion?, adjusted_intensity?}],
            "transitions": [{from_segment, to_segment, from_emotion, to_emotion, explanation}],
        }
    """
    if not classified_segments:
        return {
            "overall_sentiment": "neutral",
            "summary": "No segments to analyze.",
            "segments": [],
            "transitions": [],
        }

    client = _get_client(api_key)
    user_prompt = build_analysis_prompt(classified_segments, session_context)

    # Build model list: requested model first, then fallbacks
    models_to_try = [model] if model not in MODEL_CHAIN else []
    models_to_try += [m for m in MODEL_CHAIN if m != model]
    if model in MODEL_CHAIN:
        models_to_try.insert(0, model)

    raw_text = None
    last_error = None

    for try_model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Sending {len(classified_segments)} segments to Gemini ({try_model}), attempt {attempt + 1}...")
                # Scale token budget with segment count
                token_budget = min(65536, max(4096, len(classified_segments) * 200))
                response = client.models.generate_content(
                    model=try_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=token_budget,
                    ),
                )
                raw_text = response.text.strip()
                break  # success
            except ClientError as e:
                last_error = e
                if e.status_code == 429:
                    logger.warning(f"Rate limited on {try_model} (attempt {attempt + 1}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY_SECONDS)
                        continue
                    else:
                        logger.warning(f"Exhausted retries on {try_model}, trying next model...")
                        break  # try next model
                else:
                    logger.error(f"Gemini API error on {try_model}: {e}")
                    break  # non-retryable, try next model
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected Gemini error on {try_model}: {e}")
                break
        if raw_text is not None:
            break

    if raw_text is None:
        logger.error(f"All Gemini models failed. Last error: {last_error}")
        return {
            "overall_sentiment": "unknown",
            "summary": f"Causal analysis unavailable — Gemini API error: {str(last_error)[:200]}",
            "segments": [
                {"index": i, "trigger_phrase": None, "cause": None}
                for i in range(len(classified_segments))
            ],
            "transitions": [],
        }

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [line for line in lines if not line.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}\nRaw: {raw_text[:500]}")
        # Return a minimal valid result rather than crashing
        return {
            "overall_sentiment": "unknown",
            "summary": "Causal analysis failed — could not parse Gemini response.",
            "segments": [
                {"index": i, "trigger_phrase": None, "cause": None}
                for i in range(len(classified_segments))
            ],
            "transitions": [],
            "raw_response": raw_text[:1000],
        }

    # Validate and sanitize the result
    result.setdefault("overall_sentiment", "unknown")
    result.setdefault("summary", "")
    result.setdefault("segments", [])
    result.setdefault("transitions", [])

    logger.info(
        f"Gemini analysis complete: sentiment={result['overall_sentiment']}, "
        f"{len(result['transitions'])} transitions detected"
    )

    return result


def build_session_summary(
    classified_segments: list[dict],
    causality_result: dict,
) -> str:
    """
    Build a compact session context string from the current analysis
    for use in future multi-turn analyses.
    """
    lines = [f"Previous analysis: {causality_result.get('summary', 'N/A')}"]
    lines.append(f"Overall sentiment: {causality_result.get('overall_sentiment', 'N/A')}")

    # Summarize the emotional arc
    emotions_seen = []
    for seg in classified_segments:
        emotions_seen.append(seg["emotion"])

    if emotions_seen:
        lines.append(f"Emotional arc: {' -> '.join(emotions_seen)}")

    # Note any transitions
    transitions = causality_result.get("transitions", [])
    if transitions:
        for t in transitions:
            lines.append(
                f"Transition: {t.get('from_emotion', '?')} -> {t.get('to_emotion', '?')} "
                f"({t.get('explanation', 'unknown reason')})"
            )

    return "\n".join(lines)
