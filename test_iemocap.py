"""
IEMOCAP Pipeline Test — Tests EmotionFlow with real speech emotion data.

Uses IEMOCAP dataset (Session1, impro01) which is a ~2min improvised dialog
with known ground-truth emotion labels for comparison.
"""
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IEMOCAP_BASE = "/mnt/d/IEMOCAP_full_release"
SESSION = "Session1"
DIALOG = "Ses01F_impro01"

DIALOG_WAV = f"{IEMOCAP_BASE}/{SESSION}/dialog/wav/{DIALOG}.wav"
LABEL_FILE = f"{IEMOCAP_BASE}/{SESSION}/dialog/EmoEvaluation/{DIALOG}.txt"


def parse_iemocap_labels(label_path: str) -> list[dict]:
    """Parse IEMOCAP emotion evaluation file."""
    labels = []
    with open(label_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and "Ses" in line:
                # Format: [start - end]\tUtteranceID\tEmotion\t[V, A, D]
                parts = line.split("\t")
                time_part = parts[0]
                utt_id = parts[1].strip()
                emotion = parts[2].strip()
                # Parse timestamps
                time_part = time_part.strip("[]")
                start_str, end_str = time_part.split(" - ")
                labels.append({
                    "utterance_id": utt_id,
                    "start": float(start_str),
                    "end": float(end_str),
                    "ground_truth_emotion": emotion,
                })
    return labels


def test_with_iemocap():
    """Full pipeline test with IEMOCAP data."""
    print("=" * 70)
    print("EmotionFlow IEMOCAP Test")
    print(f"Dialog: {DIALOG}")
    print("=" * 70)

    # Check files exist
    if not os.path.exists(DIALOG_WAV):
        print(f"ERROR: Audio not found: {DIALOG_WAV}")
        return
    if not os.path.exists(LABEL_FILE):
        print(f"ERROR: Labels not found: {LABEL_FILE}")
        return

    # Parse ground truth labels
    gt_labels = parse_iemocap_labels(LABEL_FILE)
    print(f"\nGround truth: {len(gt_labels)} labeled utterances")
    emotion_counts = {}
    for l in gt_labels:
        e = l["ground_truth_emotion"]
        emotion_counts[e] = emotion_counts.get(e, 0) + 1
    print(f"  Emotion distribution: {emotion_counts}")
    print()

    # ── Run full pipeline ────────────────────────────────────────
    import redis
    from app.services.worker import process_audio_file
    from app.core.config import get_settings

    settings = get_settings()
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)

    print("Running full pipeline (fast tier)...")
    t0 = time.perf_counter()
    result = process_audio_file(
        file_path=DIALOG_WAV,
        model_tier="fast",
        user_id=0,
        session_id="iemocap-test",
        gemini_api_key=settings.GEMINI_API_KEY,
        redis_client=r,
    )
    elapsed = time.perf_counter() - t0

    # ── Print Results ────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"RESULTS  (processed in {elapsed:.1f}s)")
    print(f"{'─' * 70}")
    print(f"  Duration:          {result['duration_seconds']:.1f}s")
    print(f"  Overall sentiment: {result['overall_sentiment']}")
    print(f"  Language:          {result.get('language', 'N/A')}")
    print(f"  Model tier:        {result['model_tier']}")

    print(f"\n  Summary: {result.get('summary', 'N/A')}")

    print(f"\n{'─' * 70}")
    print(f"TRANSCRIPT ({len(result['transcript'])} segments)")
    print(f"{'─' * 70}")
    for seg in result["transcript"]:
        print(f"  [{seg['start']:6.1f}s - {seg['end']:6.1f}s] {seg['text']}")

    print(f"\n{'─' * 70}")
    print(f"EMOTION TIMELINE ({len(result['timeline'])} entries)")
    print(f"{'─' * 70}")
    for entry in result["timeline"]:
        trigger = entry.get("trigger_phrase", "—")
        cause = entry.get("cause", "—")
        print(
            f"  [{entry['timestamp_start']:6.1f}s - {entry['timestamp_end']:6.1f}s] "
            f"{entry['emotion']:12s} ({entry['intensity']:.2f})  "
            f"trigger=\"{trigger}\""
        )
        if cause and cause != "—":
            print(f"    └─ cause: {cause}")

    transitions = result.get("transitions", [])
    if transitions:
        print(f"\n{'─' * 70}")
        print(f"EMOTIONAL TRANSITIONS ({len(transitions)})")
        print(f"{'─' * 70}")
        for t in transitions:
            print(
                f"  seg {t.get('from_segment', '?')} -> seg {t.get('to_segment', '?')}: "
                f"{t.get('from_emotion', '?')} -> {t.get('to_emotion', '?')}"
            )
            print(f"    └─ {t.get('explanation', 'N/A')}")

    # ── Save full result ─────────────────────────────────────────
    os.makedirs("test_data", exist_ok=True)
    result_path = "test_data/iemocap_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nFull result saved to {result_path}")

    print(f"\n{'=' * 70}")
    print(f"IEMOCAP TEST COMPLETE — {elapsed:.1f}s total")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    test_with_iemocap()
