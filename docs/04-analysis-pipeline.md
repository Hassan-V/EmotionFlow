# Analysis Pipeline

## Overview

The analysis pipeline transforms a raw audio file into a structured timeline of emotions with
causal explanations. It runs in a **separate worker process** (not in the FastAPI event loop)
to avoid blocking the API and to allow GPU access.

```
Audio file
    │
    ▼ Step 1 — Whisper ASR
Transcript segments (start / end / text)
    │
    ▼ Step 2 — Emotion Classification
Classified segments (emotion label + intensity per segment)
    │
    ▼ Step 3 — Gemini Causality
Emotion timeline with trigger phrases + causal explanations
    │
    ▼ Write to PostgreSQL
Job result available to caller
```

---

## Model Tiers

| Tier | Whisper model | Emotion model | Gemini | VRAM | Typical latency |
|---|---|---|---|---|---|
| `fast` | `tiny` (39M) | distilroberta (6 emotions) | ✓ | ~1 GB | ~13 s |
| `balanced` | `small` (244M) | roberta-go_emotions (28 emotions) | ✓ | ~2 GB | ~17 s |
| `max` | `medium` (769M) | roberta-go_emotions (28 emotions) | ✓ | ~3 GB | ~39 s |

The models are loaded once and cached in the worker process. Whisper is unloaded from VRAM
**before** the emotion model is loaded to avoid exceeding the 6 GB limit of the GTX 1660 Super.

Tier is specified per job via the `model_tier` query parameter. The worker reads the tier from
the Redis job payload.

---

## Step 1 — ASR (`app/services/asr_service.py`)

**Input**: file path, tier  
**Output**: `{text, language, segments: [{start, end, text}], duration_seconds}`

Uses `openai-whisper`. The model is auto-detected to CUDA if available, otherwise CPU.

Key behaviours:
- The model is cached in a module-level dict `_loaded_models` — subsequent jobs with the same
  tier skip the load step (~3 s on first call, 0 s after that).
- `unload_model(tier)` frees the model from VRAM after ASR so the emotion model can load.
- If `language` is passed it overrides Whisper's auto-detection.

---

## Step 2 — Emotion Classification (`app/services/emotion_service.py`)

**Input**: list of segments from ASR  
**Output**: same list with `emotion` and `intensity` fields added per segment

Transformer pipeline runs on CUDA. Each segment's text is passed through the classifier.
Short segments (< 3 words) may map to `neutral`.

Emotion labels per tier:
- **fast / distilroberta**: anger, disgust, fear, joy, neutral, sadness, surprise
- **balanced & max / roberta-go_emotions**: 28 labels including admiration, amusement,
  annoyance, disappointment, excitement, gratitude, nervousness, relief, remorse, etc.

`unload_classifiers()` deletes the cached pipeline and calls `torch.cuda.empty_cache()`.

---

## Step 3 — Gemini Causality (`app/services/gemini_service.py`)

**Input**: classified segments, Gemini API key, optional session context  
**Output**: `{overall_sentiment, summary, segments: [{trigger_phrase, cause}], transitions}`

Sends a structured prompt to `gemini-2.5-flash` with:
- The full classified timeline (emotion + intensity + transcript text)
- Prior session context (if a `session_id` was provided)

Gemini returns:
- An `overall_sentiment` for the entire audio.
- Per-segment enrichment: the exact phrase that triggered the emotion shift, and a one-sentence
  causal explanation.
- `transitions`: list of emotion-to-emotion shifts with timestamps and explanations.

**Fallback chain**: if the primary Gemini call fails, the service retries once with a
simplified prompt before returning a default `{overall_sentiment: "unknown", ...}` result.

If `GEMINI_API_KEY` is not set, the causality step is skipped and only ASR + emotion labels
are returned.

---

## Step 4 — Session Memory (`app/services/session_service.py`)

**Input**: classified result, causality summary  
**Writes to**: Redis key `session:{user_id}:{session_id}`

Compresses the current result into a compact summary and appends it to the session's history.
On the next call with the same `session_id`, the context is fetched and injected into the
Gemini prompt so the model can reason about emotional continuity across multiple audio
segments (e.g. interview sessions, therapy recordings).

Session data is stored as JSON, TTL is 24 hours.

---

## Worker Process (`app/services/worker.py`)

### Starting the Worker

```bash
conda run --no-capture-output -n speech-emotion python -u -m app.services.worker
```

The worker uses synchronous Redis and SQLAlchemy (psycopg2) since Whisper and the Transformers
pipeline are synchronous.

### Job Processing Loop

```python
while True:
    job_id = redis.blpop("analysis:jobs", timeout=10)
    if job_id:
        process_audio_file(...)
        update PostgreSQL job record
        push telemetry to "telemetry:worker_jobs"
        publish "job.completed" to "webhook:events"
```

`blpop` blocks for up to 10 seconds before looping — this allows the process to catch
`KeyboardInterrupt` cleanly.

### Telemetry Push

After each job the worker pushes a record to `telemetry:worker_jobs`:

```json
{
  "job_id": "...",
  "user_id": "1",
  "model_tier": "balanced",
  "asr_time_ms": "1843",
  "emotion_time_ms": "412",
  "gemini_time_ms": "3201",
  "total_ms": "17344",
  "status": "completed",
  "ts": "2025-01-15T10:30:00Z"
}
```

Admins can view this data via `GET /admin/jobs/stats`.

---

## Supported Audio Formats

`.mp3`, `.wav`, `.m4a`, `.flac`  
Maximum file size: **50 MB** (configurable via `MAX_UPLOAD_SIZE_MB` in `.env`)

Files are stored in the `uploads/` directory under the project root, named by UUID to prevent
path traversal. They are not automatically deleted after processing (manual cleanup or a cron
job is needed for production).

---

## Queue Service (`app/services/queue_service.py`)

Thin wrapper around Redis `LPUSH` / `BLPOP`:

- `enqueue_analysis_job(job_id, file_path, model_tier, user_id, session_id)` — serialises job
  metadata as JSON and pushes to `analysis:jobs`.
- The worker calls the dequeue side.

The queue is a simple FIFO list. For production environments with multiple workers, each `BLPOP`
is atomic and Redis ensures exactly one worker claims each job.
