# API Reference

Base URL: `http://localhost:8000`

Authentication: `Authorization: Bearer <token>` OR `X-API-Key: ef_<key>`

---

## Health

### `GET /health`

No authentication required. Returns the live status of all backing services.

**Response `200 OK`**:
```json
{
  "status": "healthy",
  "database": "ok",
  "redis": "ok",
  "version": "1.0.0"
}
```

---

## Authentication (`/auth`)

### `POST /auth/register`

Create a new user account.

**Body**:
```json
{
  "email": "user@example.com",
  "username": "alice",         // 3-100 chars, alphanumeric/-/_
  "password": "Password1",     // ≥8 chars, 1 upper, 1 lower, 1 digit
  "full_name": "Alice"         // optional
}
```

**Responses**: `201` user object · `409` email/username taken · `422` validation error

---

### `POST /auth/login`

Exchange credentials for JWT tokens.

**Body**: `{"email": "...", "password": "..."}`

**Response `200`**: `{access_token, refresh_token, token_type: "bearer", expires_in: 1800}`

---

### `POST /auth/refresh`

Exchange a refresh token for new access + refresh tokens.

**Body**: `{"refresh_token": "..."}`

**Response `200`**: same shape as `/auth/login`

---

### `GET /auth/me`

Return the authenticated user's profile.

**Response `200`**: user object (id, email, username, role, quota_limit, quota_used_today, ...)

---

### `PATCH /auth/me`

Update the authenticated user's profile.

**Body** (all optional): `{"full_name": "...", "email": "..."}`

---

## API Keys (`/api-keys`)

All endpoints require JWT Bearer auth.

### `POST /api-keys/`

Create a new API key. Returns the raw key **once only**.

**Body**: `{"name": "My key"}` (name optional, default `"Default Key"`)

**Response `201`**: key object + `raw_key` field

Key object shape:
```json
{
  "id": 1,
  "key_prefix": "ef_abc123",
  "name": "My key",
  "is_active": true,
  "usage_count": 0,
  "last_used_at": null,
  "created_at": "2026-03-26T00:00:00Z",
  "raw_key": "ef_<44-char base64url>"  // only on creation
}

---

### `GET /api-keys/`

List all API keys for the current user (raw key never returned after creation).

**Response `200`**: array of key objects

---

### `DELETE /api-keys/{key_id}`

Permanently revoke an API key.

**Response `204`** · `404` if not found or belongs to another user

---

## Analysis (`/analysis`)

### `POST /analysis/analyze-file`

Submit an audio file for asynchronous analysis.

**Auth**: JWT Bearer or `X-API-Key`

**Request**: `multipart/form-data`
- `file` (required) — audio file: `.mp3`, `.wav`, `.m4a`, `.flac`, max 50 MB
- `model_tier` (query, default `balanced`) — `fast` | `balanced` | `max`
- `session_id` (query, optional) — up to 100 chars; enables context persistence across calls

**Response `202 Accepted`**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Analysis queued with 'balanced' tier. Poll GET /analysis/jobs/<id> for status."
}
```

**Error responses**:
- `413` — file too large
- `415` — unsupported file type
- `429` — daily quota exceeded

---

### `POST /analysis/analyze-stream`

Stream a raw audio request body without multipart encoding. HTTP chunked transfer
is accepted and the completed body is queued through the same local analysis
engine and JSON result contract as `analyze-file`.

**Auth**: JWT Bearer or `X-API-Key`

**Query**:
- `filename` (default `stream.wav`) - must end in an allowed audio extension
- `model_tier` (default `fast`) - `fast` | `balanced` | `max`
- `session_id` (optional)

**Body**: raw WAV, MP3, M4A, FLAC, OGG, or WebM bytes

```bash
curl -X POST "$BASE_URL/analysis/analyze-stream?filename=meeting.wav&model_tier=fast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: audio/wav" \
  --data-binary @meeting.wav
```

**Response**: `202 Accepted` with the same `JobSubmitResponse` as `analyze-file`.

---

### `GET /analysis/jobs/{job_id}`

Retrieve the status and result of a submitted job.

**Auth**: JWT Bearer or `X-API-Key`

**Response `200`**:

*While processing*:
```json
{
  "job_id": "550e8400-...",
  "status": "processing",
  "model_tier": "balanced",
  "created_at": "...",
  "started_at": "...",
  "completed_at": null,
  "processing_time_ms": null,
  "result": null,
  "error_message": null,
  "filename": "interview.wav",
  "file_size_bytes": 1048576
}
```

*When complete*, `result` is populated:
```json
{
  "status": "completed",
  "processing_time_ms": 17000.0,
  "result": {
    "filename": "interview.wav",
    "duration_seconds": 45.2,
    "overall_sentiment": "positive",
    "model_tier": "balanced",
    "timeline": [
      {
        "timestamp_start": 0.0,
        "timestamp_end": 5.2,
        "emotion": "neutral",
        "intensity": 0.72,
        "trigger_phrase": null,
        "cause": null
      },
      {
        "timestamp_start": 5.2,
        "timestamp_end": 11.8,
        "emotion": "joy",
        "intensity": 0.88,
        "trigger_phrase": "I finally got the offer",
        "cause": "Receiving positive news triggered a shift to joy"
      }
    ],
    "transcript": [
      {"start": 0.0, "end": 5.2, "text": "So I've been waiting for this call...", "speaker": null}
    ]
  }
}
```

**Error responses**: `404` job not found or belongs to another user

---

### `GET /analysis/jobs`

List all jobs for the current user.

**Query params**: `limit` (default 20, max 100) · `offset` (default 0)

**Response `200`**: array of job status objects

---

## Webhooks (`/webhooks`)

### `POST /webhooks/`

Register a new webhook endpoint.

**Body**:
```json
{
  "url": "https://your-server.example.com/webhooks/emotionflow",
  "name": "My server hook",
  "events": ["job.completed", "job.failed"]
}
```

Available events: `job.completed`, `job.failed`

**Response `201`**: webhook object including `secret` (signing secret, shown once)

---

### `GET /webhooks/`

List all webhooks for the current user.

---

### `GET /webhooks/{webhook_id}`

Retrieve a single webhook.

---

### `PATCH /webhooks/{webhook_id}`

Update a webhook's URL, name, events list, or active status.

---

### `DELETE /webhooks/{webhook_id}`

Delete a webhook.

---

### `POST /webhooks/{webhook_id}/test`

Trigger a test delivery to the webhook URL immediately.

**Response `200`**: `{"delivered": true, "status_code": 200, "latency_ms": 142.3}`

---

### `GET /webhooks/{webhook_id}/deliveries`

List recent delivery attempts for a webhook.

**Query params**: `limit` (default 20, max 100)

---

## Admin (`/admin`)

All endpoints require a user with `role = "admin"`.

### `GET /admin/telemetry`

High-level system metrics.

**Response `200`**:
```json
{
  "total_requests": 1042,
  "total_users": 8,
  "active_users_today": 3,
  "total_analysis_jobs": 215,
  "jobs_completed": 210,
  "jobs_failed": 2,
  "jobs_pending": 3,
  "avg_processing_time_ms": 17200.5,
  "error_rate_percent": 0.19,
  "requests_last_hour": 28
}
```

---

### `GET /admin/logs`

Recent API request log entries from the Redis telemetry stream.

**Query params**: `limit` (default 100, max 500)

---

### `GET /admin/jobs/stats`

Per-stage timing breakdown from the worker telemetry stream.

---

### `GET /admin/users`

List all users with job counts.

**Query params**: `limit` (default 50, max 200) · `offset`

---

### `PATCH /admin/users/{user_id}/quota`

Update a user's daily quota limit.

**Body**: `{"quota_limit": 500}`

---

### `GET /admin/billing/summary`

Per-user and per-tier cost breakdown for the current month.

**Response `200`**:
```json
{
  "period": "2025-01",
  "total_cost_usd": 3.45,
  "by_user": [
    {
      "user_id": 1,
      "username": "alice",
      "jobs_completed": 69,
      "total_cost_usd": 2.07,
      "breakdown": {"fast": 10, "balanced": 55, "max": 4}
    }
  ]
}
```

---

## WebSocket Streaming

### `WS /ws/stream?token={access_token}`

Send a `config` JSON message first, followed by ordered binary PCM16 frames, and finish with
`end_stream`.

**Message format**:
```json
{"type":"config","tier":"fast","session_id":"demo","encoding":"pcm_s16le","sample_rate":16000,"chunk_ms":250}
<binary 16 kHz mono PCM16 frame>
{"type":"end_stream"}
```

Server message types are `connected`, `status`, `transcript`, `emotion`, `causality`,
`final_result`, and `error`. Recoverable errors include worker loss and inactivity expiry.

---

## Common Error Shape

All error responses follow:
```json
{
  "detail": "Human-readable description"
}
```

Internal details (stack traces, DB errors) are **never** included in error responses.
They are logged internally to Redis and the server stderr.

---

## Rate Limits

- 30 requests per minute per authenticated user (keyed on `user_id`).
- 30 requests per minute per IP for unauthenticated requests.
- Response on limit: `429 Too Many Requests` with `Retry-After` header.
