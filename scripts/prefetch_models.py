#!/usr/bin/env python3
"""Download every evaluation model before enabling offline-only inference."""
from huggingface_hub import snapshot_download

MODELS = [
    "Systran/faster-whisper-base.en",
    "Systran/faster-whisper-small.en",
    "Systran/faster-whisper-medium.en",
    "j-hartmann/emotion-english-distilroberta-base",
    "superb/wav2vec2-base-superb-er",
    "Qwen/Qwen3-0.6B",
]


def main():
    for model in MODELS:
        print(f"[prefetch] {model}", flush=True)
        path = snapshot_download(repo_id=model)
        print(f"[ready] {path}", flush=True)
    print("All local models are cached. Set LOCAL_MODELS_ONLY=true.")


if __name__ == "__main__":
    main()
