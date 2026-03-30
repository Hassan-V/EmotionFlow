# Webhook System

## Overview

Webhooks allow clients to receive push notifications when a job completes or fails, instead of
polling. The delivery architecture is built on **Redis Stream Consumer Groups** for horizontal
scalability.

---

## Architecture

```
Worker process
    │  publish_event_sync(redis, "job.completed", job_id, user_id)
    ▼
Redis Stream "webhook:events"
    │  Consumer Group "webhook-dispatchers"
    ▼
Dispatcher process(es)          ← one or many, no coordination needed
    │  xreadgroup (claims messages)
    │  look up active webhooks for user_id
    │  HTTP POST to each URL with HMAC-signed payload
    │  record delivery in PostgreSQL "webhook_deliveries"
    ▼
Client server receives payload
```

Multiple dispatcher processes can run simultaneously. Redis Consumer Groups guarantee that each
event is claimed by exactly one dispatcher — there is no double-delivery risk.

---

## Managing Webhooks

### Register

```
POST /webhooks/
Authorization: Bearer <token>
Content-Type: application/json

{
  "url": "https://your-server.com/hooks/emotionflow",
  "name": "Production hook",
  "events": ["job.completed", "job.failed"]
}
```

Response `201`:
```json
{
  "id": 1,
  "url": "https://your-server.com/hooks/emotionflow",
  "name": "Production hook",
  "events": ["job.completed", "job.failed"],
  "is_active": true,
  "secret": "a1b2c3d4...64hex",   ← store this; shown only once
  "created_at": "2025-01-01T00:00:00Z"
}
```

> Store the `secret` securely. It is never returned again. If lost, delete and recreate the
> webhook to get a new secret.

### Update

```
PATCH /webhooks/{id}
{
  "url": "https://new-url.com/hook",
  "is_active": false
}
```

### Test Delivery

```
POST /webhooks/{id}/test
```

Triggers an immediate test POST to the registered URL. Useful to verify connectivity before
your first real job.

### Delivery History

```
GET /webhooks/{id}/deliveries?limit=20
```

Returns recent delivery records including HTTP status code, response body excerpt, and
retry count.

---

## Payload Format

```json
{
  "event": "job.completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "status": "completed",
    "model_tier": "balanced",
    "processing_time_ms": 17344
  }
}
```

---

## HMAC-SHA256 Signature Verification

Every delivery includes a signature header:

```
X-EmotionFlow-Signature: a3f8b2...sha256hex
X-EmotionFlow-Event: job.completed
```

The signature is computed as:

```python
import hmac, hashlib

def verify(payload_bytes: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**Receiver example (Python / Flask)**:

```python
import hmac, hashlib
from flask import request, abort

WEBHOOK_SECRET = "your-secret-from-registration"

@app.post("/hooks/emotionflow")
def receive():
    sig = request.headers.get("X-EmotionFlow-Signature", "")
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(400, "Invalid signature")
    payload = request.json
    # handle payload...
    return "", 200
```

Always use `hmac.compare_digest` (constant-time comparison) to prevent timing attacks.

---

## Retry Policy

| Attempt | Delay before retry |
|---|---|
| 1 | immediate |
| 2 | 30 s |
| 3 | 60 s |
| 4 | 120 s |
| 5 | 300 s |
| 6+ | give up — delivery marked `failed` |

A delivery is considered successful when the endpoint returns any `2xx` status code within
10 seconds.

After exhausting retries the delivery record is persisted with `status = "failed"` and
`attempts = 5`. Failed deliveries can be viewed via `GET /webhooks/{id}/deliveries`.

---

## Dispatcher Process (`app/services/webhook_service.py`)

### Starting the Dispatcher

```bash
conda run --no-capture-output -n speech-emotion python -u -m app.services.webhook_service
```

### Consumer Group Details

- Stream: `webhook:events`
- Group: `webhook-dispatchers`
- The group is created automatically if it does not exist.
- Consumers are named `dispatcher-{pid}` — each process claims its own partition.
- Processed messages are acknowledged (`xack`) after successful delivery or after all retries
  are exhausted.

### Horizontal Scaling

To double dispatch throughput start a second dispatcher in any process (local or remote):

```bash
conda run --no-capture-output -n speech-emotion python -u -m app.services.webhook_service &
conda run --no-capture-output -n speech-emotion python -u -m app.services.webhook_service &
```

Redis Consumer Groups handle coordination; no additional configuration is needed.

---

## Database Models

### `webhooks`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | int FK → users | |
| `url` | text | validated HTTPS or HTTP URL |
| `name` | varchar(100) | display label |
| `secret` | varchar(128) | hex signing secret |
| `events` | text | comma-separated event list |
| `is_active` | bool | set false to pause without deleting |
| `created_at` | timestamptz | |

### `webhook_deliveries`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `webhook_id` | int FK → webhooks | |
| `job_id` | varchar(36) | UUID of the triggering job |
| `event_type` | varchar(50) | `job.completed` / `job.failed` |
| `status` | varchar(20) | `pending` / `delivered` / `failed` |
| `attempts` | int | number of delivery attempts |
| `last_attempt_at` | timestamptz | |
| `next_retry_at` | timestamptz | null once delivered/failed |
| `response_status` | int | last HTTP response code |
| `response_body` | text | first 1000 chars of response |
| `created_at` | timestamptz | |
