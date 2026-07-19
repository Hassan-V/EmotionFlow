#!/usr/bin/env python3
"""Exercise upload, authenticated download, Redis queue, GPU worker and DB result."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AUDIO = ROOT / "test_data" / "demo_speech.wav"
OUTPUT = Path(os.getenv("EVIDENCE_OUTPUT", ROOT / "docs" / "evidence" / "local-upload-e2e-result.json"))
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def main() -> None:
    from app.core.config import get_settings

    suffix = uuid.uuid4().hex[:8]
    email = f"local-upload-{suffix}@example.com"
    username = f"localup{suffix}"
    password = "LocalTest9Pass"
    engine = create_engine(get_settings().SYNC_DATABASE_URL)
    job_id = None
    started = time.perf_counter()
    try:
        register = requests.post(
            f"{API}/auth/register",
            json={"email": email, "username": username, "password": password, "full_name": "Upload E2E"},
            timeout=30,
        )
        register.raise_for_status()
        with Session(engine) as session:
            session.execute(
                text("UPDATE users SET is_verified = TRUE WHERE email = :email"),
                {"email": email},
            )
            session.commit()

        login = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        with AUDIO.open("rb") as stream:
            submitted = requests.post(
                f"{API}/analysis/analyze-file?model_tier=fast",
                headers=headers,
                files={"file": (AUDIO.name, stream, "audio/wav")},
                timeout=60,
            )
        submitted.raise_for_status()
        job_id = submitted.json()["job_id"]

        job = None
        for _ in range(180):
            polled = requests.get(f"{API}/analysis/jobs/{job_id}", headers=headers, timeout=30)
            polled.raise_for_status()
            job = polled.json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(1)
        if not job or job["status"] != "completed":
            raise RuntimeError(f"Upload job did not complete: {job}")

        audio_response = requests.get(f"{API}/analysis/jobs/{job_id}/audio", headers=headers, timeout=30)
        audio_response.raise_for_status()
        result = job["result"]
        billing = None
        for _ in range(20):
            with Session(engine) as session:
                billing = session.execute(
                    text(
                        "SELECT status, compute_units FROM billing_events "
                        "WHERE job_id = :job_id"
                    ),
                    {"job_id": job_id},
                ).mappings().one_or_none()
            if billing:
                break
            time.sleep(0.1)
        evidence = {
            "passed": True,
            "job_id": job_id,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "processing_time_ms": job.get("processing_time_ms"),
            "authenticated_audio_download_bytes": len(audio_response.content),
            "uploaded_audio_bytes": AUDIO.stat().st_size,
            "audio_download_matches": audio_response.content == AUDIO.read_bytes(),
            "billing_event": dict(billing) if billing else None,
            "billing_event_valid": bool(
                billing and billing["status"] == "completed" and billing["compute_units"] == 1
            ),
            "timeline_segments": len(result.get("timeline", [])),
            "transition_count": len(result.get("transitions", [])),
            "has_all_modalities": all(
                {"audio", "text", "fused"}.issubset(item.get("modalities", {}))
                for item in result.get("timeline", [])
            ),
            "model_provenance": result.get("model_provenance"),
            "stage_timings": result.get("stage_timings"),
            "result": result,
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in evidence.items() if key != "result"}, indent=2))
    finally:
        with Session(engine) as session:
            user_id = session.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            ).scalar_one_or_none()
            if user_id is not None:
                session.execute(text("DELETE FROM billing_events WHERE user_id = :user_id"), {"user_id": user_id})
                session.execute(text("DELETE FROM analysis_jobs WHERE user_id = :user_id"), {"user_id": user_id})
                session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
                session.commit()
        if job_id:
            (ROOT / "uploads" / f"{job_id}.wav").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
