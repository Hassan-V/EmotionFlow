# Deployment

The production topology is a public VPS plus an RTX worker reachable over Tailscale. Do not expose Redis or PostgreSQL to the public network.

## 1. GPU worker preparation

Install Docker, the NVIDIA Container Toolkit, and Tailscale. Clone the same commit, build the worker image, then prefetch into the Docker `model_cache` volume while internet access is available:

```bash
docker compose -f docker-compose.worker.yml build worker live-worker
docker compose -f docker-compose.worker.yml run --rm live-worker python scripts/prefetch_models.py
```

Set `LOCAL_MODELS_ONLY=true`. Start the remote workers with the VPS Tailscale address in `REDIS_URL` and `DATABASE_URL`:

```bash
docker compose -f docker-compose.worker.yml up -d --build worker live-worker
```

The live worker does not publish a heartbeat until `base.en`, both emotion classifiers, and Qwen3-0.6B are resident.

## 2. VPS services

Set strong unique values for `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`, plus `TAILSCALE_IP`. Then:

```bash
docker compose -f docker-compose.prod.yml up -d --build postgres redis api frontend
curl -fsS https://emotionflow.site/health
```

Only ports 80/443 should be public. Bind database ports to the VPS Tailscale IP if the remote worker needs them. Require Redis authentication and firewall both services to the worker's Tailscale address.

## 3. Required environment

```dotenv
ENVIRONMENT=production
LOCAL_MODELS_ONLY=true
REDIS_PASSWORD=replace-with-a-long-secret
REDIS_URL=redis://:replace-with-a-long-secret@TAILSCALE_IP:6379/0
DATABASE_URL=postgresql+asyncpg://emotionflow:secret@TAILSCALE_IP:5432/emotionflow
SYNC_DATABASE_URL=postgresql+psycopg2://emotionflow:secret@TAILSCALE_IP:5432/emotionflow
JWT_SECRET_KEY=replace-with-at-least-32-random-bytes
TAILSCALE_IP=100.x.y.z
```

The frontend needs `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_MEET_PROJECT_NUMBER`, and the hosted HTTPS origin.

## 4. Google Meet developer deployment

Follow `integrations/google-meet/README.md`. The side-panel and main-stage URLs must use the same hosted HTTPS release. Enable microphone permission and allow framing by `https://meet.google.com`. The supported claim is analysis of the consenting local participant's microphone, not meeting-wide capture.

## 5. Verification and freeze

```bash
python -m unittest test_multimodal_unit.py test_protocol_unit.py
cd frontend && npm run lint && npm run build
docker compose config
curl -fsS https://emotionflow.site/health
```

After prefetch, disable outbound internet on the worker and run both an upload and a 30-second live script. Save result JSON, screenshots, model provenance, and latency readings. Freeze the commit and containers after the rehearsal.
