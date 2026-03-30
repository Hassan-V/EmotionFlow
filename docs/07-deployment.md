# Deployment Guide

## Prerequisites

| Tool | Version |
|---|---|
| Docker + Docker Compose | 24+ |
| Conda (miniconda / anaconda) | any recent |
| NVIDIA GPU + CUDA drivers | CUDA 12.6 tested |
| Python (inside conda env) | 3.9.23 |

---

## Quick Start

### 1. Start infrastructure services

```bash
cd /home/diablo/fyp-final/final-version
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port 5433 (`emotionflow` database)
- **Redis 7** on port 6380

Verify:
```bash
docker compose ps      # both containers should be "running"
redis-cli -p 6380 ping # → PONG
```

---

### 2. Configure environment

Copy and edit `.env.example`:

```bash
cp .env.example .env
```

Key settings:

```ini
# Database (matches docker-compose defaults — change only if needed)
DATABASE_URL=postgresql+asyncpg://emotionflow:emotionflow_secret@localhost:5433/emotionflow
SYNC_DATABASE_URL=postgresql+psycopg2://emotionflow:emotionflow_secret@localhost:5433/emotionflow

# Redis
REDIS_URL=redis://localhost:6380/0

# JWT (generate a real secret for production)
JWT_SECRET_KEY=change-me-in-production-use-openssl-rand-hex-32

# Gemini
GEMINI_API_KEY=your-google-ai-studio-key

# Model tier default for the worker
MODEL_TIER=balanced   # fast | balanced | max
```

Generate a secure JWT secret:
```bash
openssl rand -hex 32
```

---

### 3. Install Python dependencies

**API server dependencies** (can run on system Python with asyncpg):
```bash
conda run -n speech-emotion pip install -r requirements.txt
```

**Worker dependencies** (torch, whisper, transformers — GPU required):
```bash
conda run -n speech-emotion pip install -r requirements-worker.txt
```

---

### 4. Start the API server

```bash
conda run --no-capture-output -n speech-emotion \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API creates database tables on startup (SQLAlchemy `create_all`). Migrations via Alembic
are in `alembic/` for schema evolution.

---

### 5. Start the worker

In a separate terminal (or `tmux` pane):

```bash
conda run --no-capture-output -n speech-emotion python -u -m app.services.worker
```

---

### 6. Start the webhook dispatcher

In a third terminal:

```bash
conda run --no-capture-output -n speech-emotion python -u -m app.services.webhook_service
```

---

### 7. Verify

```bash
curl http://localhost:8000/health
# → {"status":"healthy","database":"ok","redis":"ok","version":"1.0.0"}
```

---

## Running Tests

### Integration tests (60 tests, no GPU needed)

```bash
conda run --no-capture-output -n speech-emotion python -u -m pytest test_integration.py -v
```

### End-to-end test (requires GPU + Gemini key, ~30 s)

```bash
conda run --no-capture-output -n speech-emotion python -u test_e2e_full.py
```

The E2E test spawns its own API + worker + dispatcher subprocesses — stop any running instances
first or the pre-flight cleanup will handle it.

### Tier benchmarks

```bash
conda run --no-capture-output -n speech-emotion python -u test_benchmark.py
```

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | asyncpg URL | Async DB URL for API |
| `SYNC_DATABASE_URL` | psycopg2 URL | Sync DB URL for worker |
| `REDIS_URL` | `redis://localhost:6380/0` | Redis connection |
| `JWT_SECRET_KEY` | placeholder | Must be changed in production |
| `JWT_ALGORITHM` | `HS256` | Token signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max audio file size |
| `GEMINI_API_KEY` | empty | Google AI Studio key |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `RATE_LIMIT_PER_MINUTE` | `30` | Requests / min / user or IP |
| `RATE_LIMIT_BURST` | `10` | (informational, not enforced separately) |
| `MODEL_TIER` | `balanced` | Worker default tier |

---

## Docker Compose (`docker-compose.yml`)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: emotionflow
      POSTGRES_USER: emotionflow
      POSTGRES_PASSWORD: emotionflow_secret
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
    volumes:
      - redis_data:/data
```

Non-standard ports (5433, 6380) are used to avoid conflicts with local PostgreSQL/Redis installs.

---

## Alembic Migrations

For schema changes after first deployment:

```bash
# Generate a new migration
conda run -n speech-emotion alembic revision --autogenerate -m "description"

# Apply pending migrations
conda run -n speech-emotion alembic upgrade head

# Downgrade one step
conda run -n speech-emotion alembic downgrade -1
```

---

## Scaling Notes

- **Workers**: start multiple `worker.py` processes. Redis `BLPOP` is atomic — jobs are
  claimed by exactly one worker.
- **Dispatchers**: start multiple `webhook_service.py` processes. Consumer Groups handle
  coordination.
- **API servers**: run multiple uvicorn instances behind a load balancer. All state is in
  PostgreSQL and Redis, not in memory.
- **GPU**: each worker requires a GPU (or runs on CPU with ~10× latency). Multiple CUDA
  devices can be assigned via `CUDA_VISIBLE_DEVICES=0 python -m app.services.worker`.

---

## Production Hardening Checklist

- [ ] Replace `JWT_SECRET_KEY` with a securely generated 256-bit random value.
- [ ] Set `ENVIRONMENT=production` to disable debug endpoints.
- [ ] Run API behind a reverse proxy (nginx / caddy) with TLS termination.
- [ ] Configure PostgreSQL connection pooling (PgBouncer or SQLAlchemy pool settings).
- [ ] Schedule `uploads/` cleanup cron job (audio files are not auto-deleted).
- [ ] Rotate Gemini API keys regularly.
- [ ] Add monitoring on Redis memory usage (`telemetry:api_logs` stream is capped at 50 k but
  other keys are unbounded).
- [ ] Restrict admin endpoint access by IP at the reverse proxy layer.
