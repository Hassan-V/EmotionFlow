"""Internal endpoints for worker ↔ API communication over Tailscale."""
import os

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse

from app.core.config import get_settings

router = APIRouter(prefix="/internal", tags=["Internal"])
settings = get_settings()

UPLOAD_DIR = settings.UPLOAD_DIR or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
)

# Root dir where pre-downloaded model files are stored on the VPS
# Structure: models/whisper/{name}.pt  |  models/huggingface/{model--id}/{file}
MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models"
)


@router.get("/files/{filename}")
async def download_file_for_worker(
    filename: str,
    x_worker_secret: str = Header(...),
):
    """Serve an uploaded file to the remote worker. Authenticated by shared secret."""
    if not settings.WORKER_SECRET or x_worker_secret != settings.WORKER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid worker secret")

    # Prevent path traversal
    safe = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, media_type="application/octet-stream")


@router.get("/models/{model_type}/{file_path:path}")
async def download_model_for_worker(
    model_type: str,
    file_path: str,
    x_worker_secret: str = Header(...),
):
    """
    Serve pre-downloaded ML model files to workers over Tailscale.
    model_type: 'whisper' or 'huggingface'
    file_path:  e.g. 'small.pt' or 'superb--wav2vec2-base-superb-er/pytorch_model.bin'
    """
    if not settings.WORKER_SECRET or x_worker_secret != settings.WORKER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid worker secret")

    if model_type not in ("whisper", "huggingface"):
        raise HTTPException(status_code=400, detail="Invalid model type")

    # Sanitize path to prevent traversal
    safe_path = os.path.normpath(file_path)
    if safe_path.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid path")

    full_path = os.path.join(MODELS_DIR, model_type, safe_path)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"Model file not found: {model_type}/{safe_path}")

    return FileResponse(full_path, media_type="application/octet-stream")
