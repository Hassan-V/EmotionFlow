"""
Model Sync Service — downloads ML models from VPS instead of directly from HuggingFace/OpenAI.

On worker startup, this pulls model files via the internal /internal/models/ API endpoint
over Tailscale so all workers use the exact same model versions without hitting external CDNs.

Supported model types:
  - whisper: .pt checkpoint files → ~/.cache/whisper/
  - huggingface: full model directories → TRANSFORMERS_CACHE
"""
import hashlib
import logging
import os
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("emotionflow.model_sync")

# ─── Whisper model sizes (bytes) for progress validation ───────────────────
WHISPER_MODEL_SIZES = {
    "tiny":     75_000_000,
    "small":   244_000_000,
    "medium":  769_000_000,
    "large":  1_550_000_000,
    "large-v2": 1_550_000_000,
    "large-v3": 1_550_000_000,
}

# HuggingFace model IDs → list of required files to fetch
HF_MODEL_FILES = {
    "superb/wav2vec2-base-superb-er": [
        "config.json",
        "preprocessor_config.json",
        "pytorch_model.bin",
    ],
    "superb/hubert-large-superb-er": [
        "config.json",
        "preprocessor_config.json",
        "pytorch_model.bin",
    ],
    "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition": [
        "config.json",
        "preprocessor_config.json",
        "pytorch_model.bin",
    ],
}


def _whisper_cache_dir() -> Path:
    return Path.home() / ".cache" / "whisper"


def _hf_cache_dir() -> Path:
    env = os.environ.get("TRANSFORMERS_CACHE") or os.environ.get("HF_HOME")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "huggingface" / "hub"


def _hf_model_snapshot_dir(model_id: str, cache_root: Path) -> Path:
    """Return the snapshot dir for a HuggingFace model in hub cache layout."""
    safe_id = "models--" + model_id.replace("/", "--")
    return cache_root / safe_id / "snapshots" / "main"


def _download_from_vps(
    api_base_url: str,
    worker_secret: str,
    path: str,
    dest: Path,
) -> bool:
    """
    Download a single file from the VPS internal model endpoint.
    Returns True on success, False if the file doesn't exist on VPS.
    """
    url = f"{api_base_url}/internal/models/{path}"
    headers = {"X-Worker-Secret": worker_secret}

    try:
        with requests.get(url, headers=headers, stream=True, timeout=300) as r:
            if r.status_code == 404:
                logger.warning(f"Model file not found on VPS: {path}")
                return False
            r.raise_for_status()

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            try:
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                tmp.rename(dest)
                logger.info(f"Downloaded {path} → {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
                return True
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
    except requests.RequestException as e:
        logger.error(f"Failed to download {path} from VPS: {e}")
        return False


def sync_whisper_model(model_name: str, api_base_url: str, worker_secret: str) -> bool:
    """
    Ensure the Whisper model checkpoint is available locally.
    Downloads from VPS if missing; falls back to HuggingFace CDN if VPS doesn't have it.
    Returns True if model is available.
    """
    cache_dir = _whisper_cache_dir()
    dest = cache_dir / f"{model_name}.pt"

    if dest.exists():
        logger.info(f"Whisper '{model_name}' already cached at {dest}")
        return True

    logger.info(f"Whisper '{model_name}' not found locally — fetching from VPS...")
    ok = _download_from_vps(api_base_url, worker_secret, f"whisper/{model_name}.pt", dest)

    if not ok:
        logger.warning(f"VPS doesn't have whisper/{model_name}.pt — will download from CDN on first use")

    return ok or True  # whisper.load_model handles CDN fallback transparently


def sync_hf_model(model_id: str, api_base_url: str, worker_secret: str) -> bool:
    """
    Ensure a HuggingFace model is available locally.
    Downloads files from VPS if missing; transformers will use CDN as fallback.
    Returns True if all files were available.
    """
    cache_root = _hf_cache_dir()
    snapshot_dir = _hf_model_snapshot_dir(model_id, cache_root)

    files = HF_MODEL_FILES.get(model_id, ["config.json", "pytorch_model.bin"])
    missing = [f for f in files if not (snapshot_dir / f).exists()]

    if not missing:
        logger.info(f"HF model '{model_id}' already cached")
        return True

    logger.info(f"HF model '{model_id}' missing files {missing} — fetching from VPS...")
    all_ok = True
    safe_id = model_id.replace("/", "--")

    for filename in missing:
        vps_path = f"huggingface/{safe_id}/{filename}"
        dest = snapshot_dir / filename
        ok = _download_from_vps(api_base_url, worker_secret, vps_path, dest)
        if not ok:
            all_ok = False
            logger.warning(f"VPS missing {vps_path} — transformers will download from HuggingFace Hub")

    # Write a ref file so transformers recognizes this as a valid snapshot
    ref_dir = snapshot_dir.parent.parent / "refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "main").write_text("main")

    return all_ok


def sync_all_models(api_base_url: str, worker_secret: str, model_tier: str = "balanced") -> None:
    """
    Sync all models needed for the given tier from the VPS.
    Called once at worker startup.
    """
    from app.services.asr_service import TIER_MODEL_MAP as ASR_TIER_MAP
    from app.services.audio_emotion_service import TIER_MODEL_MAP as AUDIO_TIER_MAP

    whisper_model = ASR_TIER_MAP.get(model_tier, "medium")
    audio_models = AUDIO_TIER_MAP.get(model_tier, AUDIO_TIER_MAP["balanced"])

    logger.info(f"Syncing models for tier '{model_tier}': whisper={whisper_model}, audio={audio_models}")

    sync_whisper_model(whisper_model, api_base_url, worker_secret)

    for model_id in audio_models:
        sync_hf_model(model_id, api_base_url, worker_secret)

    logger.info("Model sync complete")
