# Billing Simulation

## Overview

EmotionFlow includes a **simulated billing layer** that tracks API usage costs per user and
per tier. No real payment processing occurs — this models how a commercial SaaS API (like
Google Gemini or OpenAI APIs) would track and present costs.

---

## Pricing Model

| Tier | Cost per completed job |
|---|---|
| `fast` | $0.001 |
| `balanced` | $0.005 |
| `max` | $0.020 |

Configurable in `app/core/config.py` via `TIER_COST_FAST`, `TIER_COST_BALANCED`, `TIER_COST_MAX`.

---

## Source of Truth — `billing_events` Table

The billing layer is backed by an **append-only `billing_events` table** written by the
worker after every job. Records are never updated or deleted — this is the authoritative
ledger for dispute resolution.

A row is written for **both success and failure**:
- Completed jobs record the tier cost.
- Failed jobs record `cost_usd = 0.0` (no charge, but the attempt is auditable).

### Schema

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `job_id` | varchar(36) | FK-equivalent to `analysis_jobs.job_id` |
| `user_id` | int FK → users | SET NULL on user delete |
| `api_key_id` | int FK → api_keys | SET NULL on key delete; null = JWT auth |
| `model_tier` | varchar(20) | `fast` / `balanced` / `max` |
| `file_size_bytes` | int | null on failure |
| `audio_duration_s` | float | null on failure |
| `status` | varchar(20) | `completed` / `failed` |
| `processing_time_ms` | float | |
| `cost_usd` | float | 0.0 for failed jobs |
| `occurred_at` | timestamptz | indexed for monthly queries |

Indexes: `(user_id, occurred_at)` and `(api_key_id, occurred_at)` for fast monthly roll-ups.

---

## Cross-Reference Points for Dispute Resolution

Three independent records exist for every job:

| Record | Location | Purpose |
|---|---|---|
| `analysis_jobs` row | PostgreSQL | Job inputs, result JSON, timestamps |
| `billing_events` row | PostgreSQL | Immutable cost ledger |
| `api_keys.usage_count` | PostgreSQL | All-time call count per key (incremented on every auth) |
| `telemetry:api_logs` entry | Redis stream | Per-request log with `user_id`, `path`, timing |

---

## Billing Endpoint

```
GET /admin/billing/summary
Authorization: Bearer <admin_token>
```

**Query parameters**:
- `year` (optional, default = current year)
- `month` (optional, default = current month, 1–12)

**Response `200`**:
```json
{
  "period": "2026-03",
  "total_cost_usd": 3.455,
  "tier_rates_usd": {"fast": 0.001, "balanced": 0.005, "max": 0.02},
  "by_user": [
    {
      "user_id": 1,
      "username": "alice",
      "email": "alice@example.com",
      "jobs_completed": 69,
      "jobs_failed": 2,
      "total_cost_usd": 2.07,
      "tier_breakdown": {
        "fast":     {"completed": 10, "failed": 1, "cost_usd": 0.01},
        "balanced": {"completed": 55, "failed": 1, "cost_usd": 0.275},
        "max":      {"completed":  4, "failed": 0, "cost_usd": 0.08}
      }
    }
  ],
  "by_api_key": [
    {
      "api_key_id": 1,
      "key_prefix": "ef_abc123",
      "key_name": "Production key",
      "usage_count_total": 142,
      "user_id": 1,
      "jobs_this_period": 69,
      "cost_usd_this_period": 2.07
    }
  ]
}
```

Both `by_user` and `by_api_key` are sorted by cost descending.

---

## User-Facing Usage Summary

Regular users (not admins) can view their own usage via:

```
GET /auth/me
```

The response includes `quota_used_today` (number of analyses submitted today vs the daily
`quota_limit`). This is the primary quota enforcement mechanism — billing is a separate
concern.

---

## Quota vs Billing

| Concept | Purpose | Enforcement |
|---|---|---|
| `quota_limit` | Hard daily cap on job submissions | `429` from `/analysis/analyze-file` |
| Billing | Cost tracking for reporting / invoicing | Informational only (no hard stop) |

A real-money deployment would add a credit balance table and block submissions when the balance
is exhausted.

---

## Simulating a Full Billing Cycle

The `test_apikey_billing.py` test script demonstrates:

1. Register a new user.
2. Create a JWT session, generate an API key.
3. Submit an analysis job using only the API key (no JWT).
4. Wait for completion.
5. Verify:
   - `analysis_jobs.api_key_id` is set.
   - `api_keys.usage_count` was incremented.
   - A `BillingEvent` row was written with correct cost.
   - Telemetry is tagged with `user_id`.
   - `GET /admin/billing/summary` shows both `by_user` and `by_api_key` entries.

Run it:
```bash
conda run --no-capture-output -n speech-emotion python -u test_apikey_billing.py
```

Expected output:
```
✓ User registered: billing_<uuid>
✓ API key created: ef_abc123...
✓ Job submitted via API key: <job_id>
✓ Job completed in Xs
✓ AnalysisJob.api_key_id = <id>
✓ APIKey.usage_count = <n>
✓ APIKey.last_used_at = <timestamp>
✓ BillingEvent: tier=fast cost=$0.0010 status=completed
✓ Telemetry tagged with user_id=<id>
✓ Billing: user=billing_<uuid> jobs=1 cost=$0.001
✓ Billing per-key: key=ef_abc123 jobs=1 cost=$0.001
✓ /api-keys/ reports usage_count=<n>
All checks passed.
```

---

## Billing Endpoint

```
GET /admin/billing/summary
Authorization: Bearer <admin_token>
```

**Query parameters**:
- `year` (optional, default = current year, e.g. `2025`)
- `month` (optional, default = current month, e.g. `1`)

**Response `200`**:
```json
{
  "period": "2025-01",
  "total_cost_usd": 3.455,
  "by_user": [
    {
      "user_id": 1,
      "username": "alice",
      "email": "alice@example.com",
      "jobs_completed": 69,
      "total_cost_usd": 2.07,
      "breakdown": {
        "fast": {"jobs": 10, "cost_usd": 0.01},
        "balanced": {"jobs": 55, "cost_usd": 0.275},
        "max": {"jobs": 4, "cost_usd": 0.08}
      }
    }
  ]
}
```

The response is sorted by `total_cost_usd` descending (highest-spending users first).

---

## User-Facing Usage Summary

Regular users (not admins) can view their own usage via:

```
GET /auth/me
```

The response includes `quota_used_today` (number of analyses submitted today vs the daily
`quota_limit`). This is the primary quota enforcement mechanism — billing is a separate
concern.

---

## Quota vs Billing

| Concept | Purpose | Enforcement |
|---|---|---|
| `quota_limit` | Hard daily cap on job submissions | `429` from `/analysis/analyze-file` |
| Billing | Cost tracking for reporting / invoicing | Informational only (no hard stop) |

A real-money deployment would add a credit balance table and block submissions when the balance
is exhausted.

---

## Simulating a Full Billing Cycle

The `test_apikey_billing.py` test script demonstrates:

1. Register a new user.
2. Create a JWT session, generate an API key.
3. Submit an analysis job using only the API key (no JWT).
4. Wait for completion.
5. Verify telemetry is tagged with the user.
6. Query the billing summary as admin and verify the cost appears.

Run it:
```bash
conda run --no-capture-output -n speech-emotion python -u test_apikey_billing.py
```

Expected output:
```
✓ User registered: billing_test_<uuid>
✓ API key created: ef_abc123... (name=BillingTestKey)
✓ Job submitted via API key: <job_id>
✓ Job completed in Xs
✓ Telemetry tagged: user_id=<id> found in api_logs
✓ Billing entry: user billing_test_<uuid> | tier=balanced | cost=$0.005
✓ Total cost this month: $0.005
All checks passed.
```
