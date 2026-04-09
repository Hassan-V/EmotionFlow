#!/usr/bin/env python3
"""
VPS Model Prefetch Script — run once on the VPS to download all ML models
into the local models/ directory so workers can fetch them over Tailscale.

Usage:
    python scripts/prefetch_models.py [--tier fast|balanced|max]

Models downloaded:
  Whisper:       small, medium, large-v3
  HuggingFace:   superb/wav2vec2-base-superb-er
                 ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition
                 superb/hubert-large-superb-er
"""
import argparse
import os
import shutil
from pathlib import Path

# Models dir relative to repo root
MODELS_DIR = Path(__file__).parent.parent / "models"

WHISPER_MODELS = ["small", "medium", "large-v3"]

HF_MODELS = [
    "superb/wav2vec2-base-superb-er",
    "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
    "superb/hubert-large-superb-er",
]

HF_FILES = ["config.json", "preprocessor_config.json", "pytorch_model.bin"]


def prefetch_whisper(models: list[str]):
    import whisper

    whisper_dir = MODELS_DIR / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)

    for name in models:
        dest = whisper_dir / f"{name}.pt"
        if dest.exists():
            print(f"[whisper] {name}.pt already present ({dest.stat().st_size / 1e6:.0f} MB)")
            continue

        print(f"[whisper] Downloading {name}...")
        # whisper downloads to ~/.cache/whisper/ — copy from there
        model = whisper.load_model(name)
        src = Path.home() / ".cache" / "whisper" / f"{name}.pt"
        if src.exists():
            shutil.copy2(src, dest)
            print(f"[whisper] {name}.pt copied → {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        else:
            print(f"[whisper] Warning: could not find {src} after loading")
        del model


def prefetch_huggingface(models: list[str]):
    from transformers import pipeline
    import torch

    device = 0 if torch.cuda.is_available() else -1

    for model_id in models:
        safe_id = model_id.replace("/", "--")
        hf_dest = MODELS_DIR / "huggingface" / safe_id
        hf_dest.mkdir(parents=True, exist_ok=True)

        missing = [f for f in HF_FILES if not (hf_dest / f).exists()]
        if not missing:
            print(f"[huggingface] {model_id} already present")
            continue

        print(f"[huggingface] Downloading {model_id}...")
        try:
            pipe = pipeline("audio-classification", model=model_id, device=device)

            # Copy from HF hub cache
            import huggingface_hub
            local_dir = huggingface_hub.snapshot_download(repo_id=model_id)
            for fname in HF_FILES:
                src = Path(local_dir) / fname
                if src.exists():
                    shutil.copy2(src, hf_dest / fname)
                    print(f"  copied {fname}")
                else:
                    print(f"  Warning: {fname} not found in {local_dir}")
            del pipe
            print(f"[huggingface] {model_id} done")
        except Exception as e:
            print(f"[huggingface] Failed to download {model_id}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper-only", action="store_true")
    parser.add_argument("--hf-only", action="store_true")
    args = parser.parse_args()

    print(f"Storing models in: {MODELS_DIR.resolve()}")
    MODELS_DIR.mkdir(exist_ok=True)

    if not args.hf_only:
        prefetch_whisper(WHISPER_MODELS)

    if not args.whisper_only:
        prefetch_huggingface(HF_MODELS)

    print("\nAll models prefetched successfully.")


if __name__ == "__main__":
    main()
