# Telemetry & Observability

## Design Principles

1. **Telemetry never surfaces to callers.** The global exception handler and all admin
   endpoints are designed so that no internal detail (stack trace, DB error, internal path)
   can reach the user response body.
2. **Non-blocking writes.** The telemetry middleware writes to Redis in a fire-and-forget
   fashion. If Redis is temporarily unavailable the log entry is silently dropped — the
   request is not failed.
3. **Three-layer observability**: per-request API logs, per-job worker stage timings, and
   aggregate counters — all readable by admins via the API.

---

## Layer 1 — API Request Logs

**Middleware**: `app/middleware/telemetry.py` (`TelemetryMiddleware`)  
**Redis stream**: `telemetry:api_logs` (capped at 50 000 entries)

Every non-health request is recorded:

| Field | Example |
|---|---|
| `user_id` | `"1"` (blank for unauthenticated) |
| `path` | `"/analysis/analyze-file"` |
| `method` | `"POST"` |
| `status_code` | `"202"` |
| `process_time_ms` | `"23.14"` |
| `client_ip` | `"127.0.0.1"` |
| `user_agent` | `"python-httpx/0.27..."` |
| `error_detail` | blank unless a 4xx/5xx occurred |

The `user_id` is populated because `get_current_user` (and `get_api_key_user`) sets
`request.state.user_id` before the response returns — telemetry middleware reads that value.

**Admin endpoint**: `GET /admin/logs?limit=100`

---

## Layer 2 — Worker Stage Timings

**Worker**: `app/services/worker.py`  
**Redis stream**: `telemetry:worker_jobs` (capped at 10 000 entries)

After every job (success or failure) the worker pushes:

| Field | Example |
|---|---|
| `job_id` | UUID |
| `user_id` | `"1"` |
| `model_tier` | `"balanced"` |
| `asr_time_ms` | `"1843"` |
| `emotion_time_ms` | `"412"` |
| `gemini_time_ms` | `"3201"` |
| `total_ms` | `"17344"` |
| `status` | `"completed"` or `"failed"` |
| `ts` | ISO-8601 timestamp |

This data answers questions like *"which tier is the bottleneck?"* and *"is Gemini latency
degrading?"*.

**Admin endpoint**: `GET /admin/jobs/stats`

---

## Layer 3 — Aggregate Counters

Simple Redis `INCR` counters updated inline (no stream overhead):

| Redis key | Meaning |
|---|---|
| `telemetry:total_requests` | Lifetime request count |
| `telemetry:error_count` | Lifetime 4xx/5xx count |
| `telemetry:user:{id}:requests` | Per-user lifetime request count |

**Admin endpoint**: `GET /admin/telemetry` returns derived metrics (error rate %, requests
last hour, avg processing time, etc.).

---

## Unhandled Exception Logging

**Handler**: `app/main.py` lines 88–125 (`unhandled_exception_handler`)

When an exception escapes all route handlers:
1. The full traceback is written to Python's `logging` (stderr in production).
2. A sanitised entry (exception type + 300-char message, no traceback) is appended to
   `telemetry:api_logs`.
3. `telemetry:error_count` is incremented.
4. A generic `{"detail": "An internal error occurred. Please try again later."}` is returned
   to the caller — nothing leaks.

---

## Rate Limit Events

`RateLimitMiddleware` returns `429` before any route handler runs. These 429 responses are
recorded like any other request in `telemetry:api_logs` (status_code = `"429"`). The global
error counter is also incremented (since 429 ≥ 400).

---

## Billing Telemetry

**Admin endpoint**: `GET /admin/billing/summary`

Cost is calculated from completed `AnalysisJob` records using the configured per-tier pricing:

| Tier | Cost per job |
|---|---|
| `fast` | $0.001 |
| `balanced` | $0.005 |
| `max` | $0.020 |

These are **simulated billing rates** for demonstration. The endpoint aggregates by user and
tier for the current calendar month and returns a cost breakdown. No actual payment processing
is involved.

---

## Accessing Telemetry

All admin endpoints require `role = "admin"`. A user can be promoted to admin directly in
PostgreSQL:

```sql
UPDATE users SET role = 'admin' WHERE username = 'alice';
```

Or via the admin panel (if a front-end is wired up).

### Quick admin CLI check

```bash
# Tail the API log stream (last 5 entries)
redis-cli -p 6380 XREVRANGE telemetry:api_logs + - COUNT 5

# Worker job timings
redis-cli -p 6380 XREVRANGE telemetry:worker_jobs + - COUNT 5

# Error count
redis-cli -p 6380 GET telemetry:error_count

# Per-user requests
redis-cli -p 6380 GET telemetry:user:1:requests
```

---

## Privacy Constraints

- Per-request logs contain `user_id` (internal integer) and `client_ip` — no PII beyond that.
- No request/response body content is logged.
- Admin log endpoints are not pageable by regular users (403 Forbidden).
- Worker telemetry contains only timing data and job IDs — no audio content or transcript text.
