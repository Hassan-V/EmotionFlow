#!/usr/bin/env python3
"""Exercise authenticated chunked HTTP audio upload through the real worker."""
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
OUTPUT = Path(os.getenv("EVIDENCE_OUTPUT", ROOT / "docs" / "evidence" / "local-rest-stream-result.json"))
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def audio_chunks():
    with AUDIO.open("rb") as stream:
        while chunk := stream.read(8192):
            yield chunk


def main() -> None:
    from app.core.config import get_settings

    suffix = uuid.uuid4().hex[:8]
    email = f"local-stream-{suffix}@example.com"
    username = f"localstream{suffix}"
    password = "LocalTest9Pass"
    engine = create_engine(get_settings().SYNC_DATABASE_URL)
    job_id = None
    started = time.perf_counter()
    try:
        register = requests.post(
            f"{API}/auth/register",
            json={"email": email, "username": username, "password": password, "full_name": "REST Stream E2E"},
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
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "Content-Type": "audio/wav",
        }
        submitted = requests.post(
            f"{API}/analysis/analyze-stream?filename=demo-stream.wav&model_tier=fast",
            headers=headers,
            data=audio_chunks(),
            timeout=60,
        )
        submitted.raise_for_status()
        self_timing_header_ms = float(submitted.headers["X-Process-Time-Ms"])
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
            raise RuntimeError(f"REST stream job did not complete: {job}")

        result = job["result"]
        evidence = {
            "passed": True,
            "transport": "HTTP chunked request body",
            "job_id": job_id,
            "submit_api_latency_ms": self_timing_header_ms,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "processing_time_ms": job.get("processing_time_ms"),
            "streamed_audio_bytes": AUDIO.stat().st_size,
            "timeline_segments": len(result.get("timeline", [])),
            "transition_count": len(result.get("transitions", [])),
            "has_transcript": bool(result.get("transcript")),
            "has_causes": any(item.get("cause") for item in result.get("timeline", [])),
            "external_inference": result.get("model_provenance", {}).get("external_inference"),
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
