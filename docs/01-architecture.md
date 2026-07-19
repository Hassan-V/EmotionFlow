# EmotionFlow Architecture

EmotionFlow runs inference locally and uses the same multimodal analyzer for uploaded files and live PCM audio. No external inference API is required.

```text
Browser / Meet add-on
  |  HTTPS + authenticated WebSocket
  v
FastAPI on VPS ---- PostgreSQL
  |
  | Redis queues and session channels over Tailscale
  v
RTX live/file workers
  |- Faster-Whisper ASR
  |- Wav2Vec2 audio emotion
  |- DistilRoBERTa text emotion
  |- TF-IDF topics + acoustic measurements
  |- 55/45 fusion + deterministic hysteresis
  `- Qwen3-0.6B explanation with deterministic fallback
```

## Trust boundaries

- FastAPI authenticates users and WebSocket sessions; the browser never connects to Redis.
- PostgreSQL and Redis bind only to localhost or the Tailscale interface in production.
- Redis requires authentication. Audio downloads remain behind the authenticated API route.
- Workers advertise readiness with 30-second heartbeat keys only after all live models load.
- Session queues, result channels, and state expire after 15 minutes.

## Live flow

The browser uses an `AudioWorklet` to send 16 kHz mono PCM16 frames every 250 ms. FastAPI selects a ready live worker and routes frames to its Redis queue. The worker analyzes three-second windows with 500 ms overlap, and publishes transcript, emotion, causality, and final-result messages to a session-specific Redis channel. FastAPI relays those messages to the authenticated browser.

Live inference has priority because it is handled by a dedicated worker process. On a shared GPU, file workers should be paused or limited while the live worker owns the device.

## File flow

Uploads are persisted by FastAPI and placed on the existing RQ queue. The file worker transcribes and analyzes every segment through the same `analyze_multimodal_segments` engine, saves the compatible timeline plus extended multimodal evidence, and publishes telemetry.

## Offline model policy

Run `python scripts/prefetch_models.py` on the GPU worker before deployment. Production sets `LOCAL_MODELS_ONLY=true`; a missing model fails worker startup instead of downloading during a demo.
