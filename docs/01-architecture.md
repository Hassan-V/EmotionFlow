# EmotionFlow — System Architecture

## Overview

EmotionFlow is a SaaS API for **temporal emotion profiling and causal analysis** of audio files.
A caller submits an audio file, the system transcribes it (Whisper ASR), classifies emotions
per time segment (Transformer classifier), and then runs a causal reasoning pass (Gemini 2.5
Flash) to explain emotional transitions and surface trigger phrases.

Results are returned asynchronously via polling or webhook callbacks.

---

## Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| API server | FastAPI (async) | Python 3.9, port 8000 |
| Database | PostgreSQL 16-alpine | Port 5433, schema `emotionflow` |
| Cache / queue | Redis 7-alpine | Port 6380 |
| AI worker | PyTorch 2.7 + openai-whisper | Runs in `speech-emotion` conda env |
| Emotion model (fast) | `j-hartmann/emotion-english-distilroberta-base` | 6 emotions |
| Emotion model (balanced/max) | `SamLowe/roberta-base-go_emotions` | 28 emotions |
| Whisper (fast) | `tiny` — ~145 MB VRAM | |
| Whisper (balanced) | `small` — ~932 MB VRAM | default tier |
| Whisper (max) | `medium` — ~2.9 GB VRAM | |
| Causality | Google Gemini 2.5 Flash | REST API via `google-genai` |
| ORM | SQLAlchemy 2.0 async (asyncpg) | Sync path (psycopg2) for worker |
| Auth | JWT HS256 + bcrypt + API keys | python-jose, passlib |
| Webhooks | Redis Stream Consumer Groups | Horizontally scalable |

---

## Component Map

```
┌────────────────────────────────────────────────────────────┐
│                     Client (HTTP)                          │
└────────────────────────┬───────────────────────────────────┘
                         │ REST / WebSocket
┌────────────────────────▼───────────────────────────────────┐
│                    FastAPI (app/)                          │
│  middleware/telemetry.py  ──► Redis "telemetry:api_logs"   │
│  middleware/rate_limit.py ──► Redis "ratelimit:*"          │
│  routers/auth.py          ──► PostgreSQL users / api_keys  │
│  routers/analysis.py      ──► PostgreSQL analysis_jobs     │
│                                   └─► Redis "analysis:jobs"│
│  routers/api_keys.py      ──► PostgreSQL api_keys          │
│  routers/webhooks.py      ──► PostgreSQL webhooks          │
│  routers/admin.py         ──► Redis + PostgreSQL (read)    │
│  routers/streaming.py     ──► WebSocket job status stream  │
└────────────────────────────────────────────────────────────┘
          │  enqueue job                  │  publish event
          ▼                               ▼
┌──────────────────┐          ┌───────────────────────┐
│  Redis Queue     │          │  Redis Stream         │
│  "analysis:jobs" │          │  "webhook:events"     │
└────────┬─────────┘          └──────────┬────────────┘
         │ dequeue                        │ consume group
┌────────▼─────────┐          ┌──────────▼────────────┐
│  Worker process  │          │  Dispatcher process   │
│  services/       │          │  webhook_service.py   │
│   asr_service    │          │  HMAC-SHA256 signing  │
│   emotion_service│          │  retry backoff        │
│   gemini_service │          │  PostgreSQL delivery  │
│   session_service│          │  log                  │
└────────┬─────────┘          └───────────────────────┘
         │ write result
┌────────▼─────────┐
│   PostgreSQL     │
│  analysis_jobs   │
│  (result JSON)   │
└──────────────────┘
```

---

## Request Lifecycle

1. **Auth** — Client authenticates via `POST /auth/login` (JWT) or presents `X-API-Key` header.
2. **Submit** — `POST /analysis/analyze-file` validates the file, records a job in PostgreSQL,
   enqueues the job ID to Redis, returns `202 Accepted` with `job_id`.
3. **Process** — The worker pulls the job from Redis, runs the 3-stage AI pipeline, writes
   structured results back to `analysis_jobs`, publishes a `job.completed` event to the
   webhook stream.
4. **Poll / Stream** — Client polls `GET /analysis/jobs/{job_id}` or subscribes via WebSocket
   `WS /streaming/jobs/{job_id}` to get live status updates.
5. **Webhook** — The dispatcher consumes the `webhook:events` stream, finds all active webhooks
   for the user, POSTs signed payloads to each registered URL.

---

## Middleware Stack (execution order: top = first)

```
Request →  CORSMiddleware
        →  RateLimitMiddleware  (Redis token bucket, 30 req/min)
        →  TelemetryMiddleware  (logs every request to Redis stream)
        →  Route handler
        →  Global exception handler (strips all internals from 500 responses)
```

---

## Redis Key Space

| Key / Stream | Type | Purpose |
|---|---|---|
| `analysis:jobs` | List (queue) | Pending job IDs for worker |
| `webhook:events` | Stream | Job completion events for dispatcher |
| `telemetry:api_logs` | Stream | Per-request API telemetry (capped 50 k) |
| `telemetry:worker_jobs` | Stream | Per-job worker stage timings (capped 10 k) |
| `telemetry:total_requests` | String (int) | Running request counter |
| `telemetry:error_count` | String (int) | Running error counter |
| `telemetry:user:{id}:requests` | String (int) | Per-user request counter |
| `ratelimit:user:{id}` / `ratelimit:ip:{ip}` | String (int) | Rate limit windows |
| `session:{user_id}:{session_id}` | String (JSON) | Gemini session memory |

---

## Process Topology

A full production deployment runs three OS processes:

```
process 1: uvicorn app.main:app          # API server
process 2: python -m app.services.worker # AI pipeline worker
process 3: python -m app.services.webhook_service  # webhook dispatcher
```

Multiple workers and dispatchers can run simultaneously — Redis queues and Consumer Groups
handle coordination automatically (horizontal scale-out).

---

## Security Model

- Passwords hashed with bcrypt (12 rounds).
- JWT access tokens expire in 30 minutes; refresh tokens in 7 days.
- API keys are stored as bcrypt hashes — the raw key is returned only once at creation.
- Webhook payloads are HMAC-SHA256 signed with a per-webhook secret.
- All unhandled exceptions are caught by the global exception handler; internal error
  details never appear in API responses.
- Admin-only endpoints check `user.role == "admin"` before executing.
- Rate limiting falls back to allow-through if Redis is temporarily unavailable.
