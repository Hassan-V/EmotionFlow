#!/usr/bin/env python3
"""Exercise the authenticated WebSocket, Redis routing, and real live GPU worker."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AUDIO = ROOT / "test_data" / "demo_speech.wav"
OUTPUT = Path(os.getenv("EVIDENCE_OUTPUT", ROOT / "docs" / "evidence" / "local-websocket-result.json"))
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EXPECT_NO_WORKER = os.getenv("EXPECT_NO_WORKER", "").lower() in {"1", "true", "yes"}


async def run_stream(token: str):
    import librosa
    import numpy as np
    import soundfile as sf
    import websockets

    waveform, rate = sf.read(AUDIO, dtype="float32", always_2d=False)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    if rate != 16000:
        waveform = librosa.resample(waveform, orig_sr=rate, target_sr=16000)
    pcm = (np.clip(waveform, -1, 1) * 32767).astype("<i2")
    frames = [pcm[index:index + 4000].tobytes() for index in range(0, len(pcm), 4000)]

    messages = []
    latencies = []
    started = time.perf_counter()
    uri = f"{API.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)}/ws/stream?token={token}"
    async with websockets.connect(uri, max_size=8 * 1024 * 1024) as socket:
        connected = json.loads(await socket.recv())
        if EXPECT_NO_WORKER:
            assert connected["type"] == "error"
            assert connected.get("recoverable") is True
            assert "worker" in connected.get("message", "").lower()
            return {
                "passed": True,
                "message_types": ["error"],
                "message_count": 1,
                "p95_latency_ms": None,
                "p95_under_five_seconds": False,
                "final_result": {},
                "error": connected,
            }
        assert connected["type"] == "connected"
        messages.append(connected)
        await socket.send(json.dumps({
            "type": "config",
            "tier": "fast",
            "session_id": "local-websocket-test",
            "encoding": "pcm_s16le",
            "sample_rate": 16000,
            "chunk_ms": 250,
        }))

        async def sender():
            loop = asyncio.get_running_loop()
            next_deadline = loop.time()
            for frame in frames:
                await socket.send(frame)
                next_deadline += 0.25
                await asyncio.sleep(max(0.0, next_deadline - loop.time()))
            await socket.send(json.dumps({"type": "end_stream"}))

        send_task = asyncio.create_task(sender())
        final = None
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=45))
            messages.append(message)
            if message.get("latency_ms") is not None:
                latencies.append(float(message["latency_ms"]))
            if message["type"] == "error":
                raise RuntimeError(message["message"])
            if message["type"] == "final_result":
                final = message["result"]
                break
        await send_task

    sorted_latency = sorted(latencies)
    p95 = sorted_latency[min(len(sorted_latency) - 1, int(len(sorted_latency) * 0.95))] if sorted_latency else None
    return {
        "passed": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "message_types": sorted({message["type"] for message in messages}),
        "message_count": len(messages),
        "latency_samples_ms": latencies,
        "p95_latency_ms": p95,
        "p95_under_five_seconds": p95 is not None and p95 <= 5000,
        "final_result": final,
    }


def main():
    import requests
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.core.config import get_settings

    suffix = uuid.uuid4().hex[:8]
    email = f"local-e2e-{suffix}@example.com"
    username = f"locale2e{suffix}"
    password = "LocalTest9Pass"
    response = requests.post(f"{API}/auth/register", json={
        "email": email, "username": username, "password": password, "full_name": "Local E2E"
    }, timeout=30)
    response.raise_for_status()

    engine = create_engine(get_settings().SYNC_DATABASE_URL)
    try:
        with Session(engine) as session:
            session.execute(
                text("UPDATE users SET is_verified = TRUE WHERE email = :email"),
                {"email": email},
            )
            session.commit()
        login = requests.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        login.raise_for_status()
        result = asyncio.run(run_stream(login.json()["access_token"]))
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({
            "output": str(OUTPUT),
            "message_types": result["message_types"],
            "message_count": result["message_count"],
            "p95_latency_ms": result["p95_latency_ms"],
            "p95_under_five_seconds": result["p95_under_five_seconds"],
            "segments": len(result["final_result"].get("timeline", [])),
            "transitions": len(result["final_result"].get("transitions", [])),
        }, indent=2))
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
            session.commit()


if __name__ == "__main__":
    main()
