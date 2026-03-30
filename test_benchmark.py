"""
Tier Comparison Benchmark — Runs the same IEMOCAP dialog through all 3 tiers
and compares transcription quality, latency, and GPU memory usage.
"""
import sys
import os
import time
import json
import gc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IEMOCAP_BASE = "/mnt/d/IEMOCAP_full_release"
DIALOG_WAV = f"{IEMOCAP_BASE}/Session1/dialog/wav/Ses01F_impro01.wav"

def get_gpu_mem():
    """Return (used_MB, total_MB) or None."""
    try:
        import torch
        if torch.cuda.is_available():
            used = torch.cuda.memory_allocated() / 1024**2
            reserved = torch.cuda.memory_reserved() / 1024**2
            total = torch.cuda.get_device_properties(0).total_memory / 1024**2
            return round(used, 1), round(reserved, 1), round(total, 1)
    except Exception:
        pass
    return 0, 0, 0


def benchmark_tier(tier: str):
    """Run a single tier and return timing + quality metrics."""
    import torch
    from app.services.asr_service import load_model as load_whisper, unload_model
    from app.services.emotion_service import classify_segments, unload_classifiers
    import whisper as whisper_mod

    # Clean slate
    torch.cuda.empty_cache()
    gc.collect()

    results = {"tier": tier}

    # ── ASR: separate model load from inference ──────────────────
    print(f"\n  [{tier}] Loading Whisper model to GPU...")
    t_load = time.perf_counter()
    model = load_whisper(tier)
    load_time = time.perf_counter() - t_load
    gpu_after_load = get_gpu_mem()
    results["asr_load_s"] = round(load_time, 1)
    results["asr_model_gpu_mb"] = gpu_after_load[0]

    print(f"  [{tier}] Transcribing audio...")
    t_infer = time.perf_counter()
    # Use whisper directly since model is already loaded
    raw = model.transcribe(DIALOG_WAV, language="en", fp16=(str(model.device) != "cpu"))
    asr_infer_time = time.perf_counter() - t_infer

    # Build segments same as asr_service
    segments = []
    for seg in raw["segments"]:
        segments.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip()
        })
    asr_result = {
        "text": raw["text"],
        "language": raw.get("language", "en"),
        "segments": segments,
        "duration_seconds": segments[-1]["end"] if segments else 0
    }

    results["asr_infer_s"] = round(asr_infer_time, 1)
    results["asr_total_s"] = round(load_time + asr_infer_time, 1)
    results["asr_gpu_alloc_mb"] = gpu_after_load[0]
    results["segments"] = len(asr_result["segments"])
    results["duration_s"] = asr_result["duration_seconds"]
    results["language"] = asr_result["language"]
    results["transcript_preview"] = asr_result["text"][:500]

    # Free ASR before emotion
    unload_model(tier)
    torch.cuda.empty_cache()

    # ── Emotion Classification ────────────────────────────────────
    print(f"  [{tier}] Running emotion classification...")
    t0 = time.perf_counter()
    classified = classify_segments(asr_result["segments"], tier=tier)
    emo_time = time.perf_counter() - t0
    gpu_after_emo = get_gpu_mem()

    results["emo_time_s"] = round(emo_time, 1)
    results["emo_gpu_alloc_mb"] = gpu_after_emo[0]
    results["emo_gpu_reserved_mb"] = gpu_after_emo[1]

    # Emotion distribution
    emo_counts = {}
    for seg in classified:
        e = seg["emotion"]
        emo_counts[e] = emo_counts.get(e, 0) + 1
    results["emotion_distribution"] = emo_counts

    # Free emotion
    unload_classifiers()
    torch.cuda.empty_cache()

    results["total_time_s"] = round(results["asr_total_s"] + results["emo_time_s"], 1)
    results["infer_only_s"] = round(results["asr_infer_s"] + results["emo_time_s"], 1)
    results["realtime_factor"] = round(results["duration_s"] / results["infer_only_s"], 2) if results["infer_only_s"] > 0 else 0

    return results, asr_result, classified


def print_comparison(all_results):
    """Print a side-by-side comparison table."""
    print(f"\n{'=' * 80}")
    print("TIER COMPARISON RESULTS")
    print(f"{'=' * 80}")
    print(f"Audio: Ses01F_impro01.wav (~132s improvised dialog)")
    print(f"GPU: NVIDIA GeForce GTX 1660 SUPER (6GB)")
    print()

    # Header
    tiers = [r["tier"] for r in all_results]
    print(f"{'Metric':<30} ", end="")
    for t in tiers:
        print(f"{'[' + t + ']':>16}", end="")
    print()
    print("-" * (30 + 16 * len(tiers)))

    rows = [
        ("ASR Model Load (s)", "asr_load_s"),
        ("ASR Inference (s)", "asr_infer_s"),
        ("Emotion (s)", "emo_time_s"),
        ("Total w/ Load (s)", "total_time_s"),
        ("Inference Only (s)", "infer_only_s"),
        ("Realtime Factor (x)", "realtime_factor"),
        ("Transcript Segments", "segments"),
        ("ASR Model VRAM (MB)", "asr_model_gpu_mb"),
        ("Emotion VRAM (MB)", "emo_gpu_alloc_mb"),
    ]

    for label, key in rows:
        print(f"{label:<30} ", end="")
        for r in all_results:
            val = r.get(key, "N/A")
            if isinstance(val, float):
                print(f"{val:>16.1f}", end="")
            else:
                print(f"{str(val):>16}", end="")
        print()

    # Emotion distributions
    print()
    all_emotions = set()
    for r in all_results:
        all_emotions.update(r.get("emotion_distribution", {}).keys())
    for emo in sorted(all_emotions):
        print(f"  {emo:<26} ", end="")
        for r in all_results:
            count = r.get("emotion_distribution", {}).get(emo, 0)
            print(f"{count:>16}", end="")
        print()

    # Transcript quality comparison
    print(f"\n{'=' * 80}")
    print("TRANSCRIPT COMPARISON (first 500 chars)")
    print(f"{'=' * 80}")
    for r in all_results:
        print(f"\n--- [{r['tier']}] ---")
        print(r.get("transcript_preview", "N/A"))

    # Cost estimation
    print(f"\n{'=' * 80}")
    print("ESTIMATED COMPUTE COSTS (cloud pricing)")
    print(f"{'=' * 80}")
    print(f"{'':30} ", end="")
    for t in tiers:
        print(f"{'[' + t + ']':>16}", end="")
    print()
    print("-" * (30 + 16 * len(tiers)))

    # AWS g4dn.xlarge (T4 GPU): ~$0.526/hr = $0.0001461/s
    gpu_cost_per_s = 0.0001461
    for r in all_results:
        r["cost_per_min_audio"] = round(r["infer_only_s"] / r["duration_s"] * 60 * gpu_cost_per_s, 6)
        r["cost_per_hour_audio"] = round(r["cost_per_min_audio"] * 60, 4)
        r["throughput_min_per_hour"] = round(3600 / r["infer_only_s"] * r["duration_s"] / 60, 1) if r["infer_only_s"] > 0 else 0

    cost_rows = [
        ("GPU cost/min audio ($)", "cost_per_min_audio"),
        ("GPU cost/hour audio ($)", "cost_per_hour_audio"),
        ("Throughput (min audio/hr)", "throughput_min_per_hour"),
    ]
    for label, key in cost_rows:
        print(f"{label:<30} ", end="")
        for r in all_results:
            val = r.get(key, 0)
            if key.startswith("cost"):
                print(f"${val:>14.4f}", end="")
            else:
                print(f"{val:>16.1f}", end="")
        print()

    # Gemini API costs (not tested here, fixed cost)
    print(f"\n+ Gemini 2.5 Flash API: ~$0.15/1M input tokens, ~$0.60/1M output tokens")
    print(f"  (~$0.001-0.003 per analysis depending on transcript length)")
    print(f"\nNote: GPU costs based on AWS g4dn.xlarge ($0.526/hr, T4 GPU)")
    print(f"      Your GTX 1660 Super = free (local), similar perf to T4")


if __name__ == "__main__":
    import torch
    print("=" * 80)
    print("EmotionFlow Tier Benchmark")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB" if torch.cuda.is_available() else "")
    print("=" * 80)

    tiers_to_test = ["fast", "balanced", "max"]
    all_results = []
    all_transcripts = {}

    for tier in tiers_to_test:
        print(f"\n{'─' * 60}")
        print(f"BENCHMARKING: {tier.upper()} tier")
        print(f"{'─' * 60}")
        try:
            result, asr, classified = benchmark_tier(tier)
            all_results.append(result)
            all_transcripts[tier] = asr
            print(f"  [{tier}] DONE — {result['total_time_s']}s total, {result['segments']} segments")
        except Exception as e:
            print(f"  [{tier}] FAILED: {e}")
            import traceback
            traceback.print_exc()

    if all_results:
        print_comparison(all_results)

        # Save raw results
        os.makedirs("test_data", exist_ok=True)
        with open("test_data/tier_benchmark.json", "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nRaw results saved to test_data/tier_benchmark.json")
