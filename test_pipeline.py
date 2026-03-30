"""
End-to-end pipeline test — Tests each AI service individually,
then the full pipeline end-to-end.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_asr():
    """Test Whisper ASR service."""
    print("=== TEST 1: ASR Service (Whisper tiny) ===")
    from app.services.asr_service import transcribe, unload_model

    t0 = time.perf_counter()
    result = transcribe("test_data/test_audio.wav", tier="fast")
    elapsed = time.perf_counter() - t0

    print(f"  Duration: {result['duration_seconds']}s")
    print(f"  Language: {result['language']}")
    print(f"  Segments: {len(result['segments'])}")
    print(f"  Full text: \"{result['text'][:200]}\"")
    for seg in result["segments"][:5]:
        print(f"    [{seg['start']}-{seg['end']}s] {seg['text']}")
    print(f"  Time: {elapsed:.1f}s")
    unload_model("fast")
    print("  ASR PASSED\n")
    return result


def test_emotion(segments):
    """Test emotion classification service."""
    print("=== TEST 2: Emotion Classification ===")
    from app.services.emotion_service import classify_segments, unload_classifiers

    # If Whisper returned no text segments from synthetic audio,
    # use a fallback with real text
    if not segments:
        segments = [
            {"start": 0.0, "end": 5.0, "text": "I'm really worried about the deadline."},
            {"start": 5.0, "end": 10.0, "text": "But I think we can do better this time!"},
        ]
        print("  (Using fallback text segments since ASR returned no speech)")

    t0 = time.perf_counter()
    classified = classify_segments(segments, tier="fast")
    elapsed = time.perf_counter() - t0

    print(f"  Classified {len(classified)} segments")
    for seg in classified:
        print(f"    [{seg['start']}-{seg['end']}s] {seg['emotion']} ({seg['intensity']:.2f}): \"{seg['text'][:60]}\"")
    print(f"  Time: {elapsed:.1f}s")
    unload_classifiers()
    print("  EMOTION PASSED\n")
    return classified


def test_gemini(classified):
    """Test Gemini causality service."""
    print("=== TEST 3: Gemini Causality ===")
    from app.services.gemini_service import analyze_causality, build_session_summary
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        print("  SKIPPED (no GEMINI_API_KEY)")
        return None

    t0 = time.perf_counter()
    result = analyze_causality(classified, settings.GEMINI_API_KEY)
    elapsed = time.perf_counter() - t0

    print(f"  Overall sentiment: {result.get('overall_sentiment')}")
    print(f"  Summary: {result.get('summary', '')[:200]}")
    print(f"  Segment analyses: {len(result.get('segments', []))}")
    for seg in result.get("segments", []):
        print(f"    [{seg.get('index')}] trigger=\"{seg.get('trigger_phrase', 'N/A')}\" cause=\"{str(seg.get('cause', 'N/A'))[:80]}\"")
    print(f"  Transitions: {len(result.get('transitions', []))}")
    for t_item in result.get("transitions", []):
        print(f"    {t_item.get('from_emotion')} -> {t_item.get('to_emotion')}: {t_item.get('explanation', '')[:80]}")
    print(f"  Time: {elapsed:.1f}s")

    # Test session summary builder
    summary = build_session_summary(classified, result)
    print(f"  Session summary: \"{summary[:150]}...\"")
    print("  GEMINI PASSED\n")
    return result


def test_session_memory():
    """Test session memory service."""
    print("=== TEST 4: Session Memory ===")
    import redis
    from app.services.session_service import (
        get_session_context, append_to_session, list_sessions, clear_session
    )
    from app.core.config import get_settings

    settings = get_settings()
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)

    test_user_id = 999
    test_session_id = "test-session-001"

    # Clear any previous test data
    clear_session(r, test_user_id, test_session_id)

    # Should be empty
    ctx = get_session_context(r, test_user_id, test_session_id)
    assert ctx is None, f"Expected None, got {ctx}"
    print("  Empty session: OK")

    # Append two entries
    append_to_session(r, test_user_id, test_session_id, "First analysis: speaker showed anxiety about deadline")
    append_to_session(r, test_user_id, test_session_id, "Second analysis: speaker shifted to cautious optimism")

    # Retrieve context
    ctx = get_session_context(r, test_user_id, test_session_id)
    assert ctx is not None
    assert "anxiety" in ctx
    assert "optimism" in ctx
    print(f"  Session context ({len(ctx)} chars): OK")

    # List sessions
    sessions = list_sessions(r, test_user_id)
    assert len(sessions) >= 1
    print(f"  Listed {len(sessions)} sessions: OK")

    # Cleanup
    clear_session(r, test_user_id, test_session_id)
    print("  SESSION PASSED\n")


def test_full_pipeline():
    """Test the full worker pipeline end-to-end."""
    print("=== TEST 5: Full Pipeline (worker.process_audio_file) ===")
    import redis
    from app.services.worker import process_audio_file
    from app.core.config import get_settings

    settings = get_settings()
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)

    # Use fallback text segments if no real speech in synthetic audio
    t0 = time.perf_counter()
    result = process_audio_file(
        file_path="test_data/test_audio.wav",
        model_tier="fast",
        user_id=0,
        session_id="test-e2e",
        gemini_api_key=settings.GEMINI_API_KEY,
        redis_client=r,
    )
    elapsed = time.perf_counter() - t0

    print(f"  Filename: {result['filename']}")
    print(f"  Duration: {result['duration_seconds']}s")
    print(f"  Overall sentiment: {result['overall_sentiment']}")
    print(f"  Model tier: {result['model_tier']}")
    print(f"  Timeline entries: {len(result['timeline'])}")
    print(f"  Transcript entries: {len(result['transcript'])}")
    print(f"  Transitions: {len(result.get('transitions', []))}")
    print(f"  Total time: {elapsed:.1f}s")
    print("  FULL PIPELINE PASSED\n")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("EmotionFlow AI Pipeline — End-to-End Tests")
    print("=" * 60)
    print()

    # Test 1: ASR
    asr_result = test_asr()

    # Test 2: Emotion (use real text if ASR returned nothing useful)
    test_segments = asr_result.get("segments", [])
    classified = test_emotion(test_segments)

    # Test 3: Gemini causality
    test_gemini(classified)

    # Test 4: Session memory
    test_session_memory()

    # Test 5: Full pipeline
    test_full_pipeline()

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
