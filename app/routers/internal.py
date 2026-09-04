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
