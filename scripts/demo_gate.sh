#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/6] Python syntax and deterministic/protocol tests"
.venv/bin/python -m compileall -q app scripts test_multimodal_unit.py test_protocol_unit.py test_proposal_compliance.py
.venv/bin/python -m unittest test_multimodal_unit.py test_protocol_unit.py test_proposal_compliance.py

echo "[2/6] Frontend lint and production build"
(cd frontend && npm run lint && npm run build)

echo "[3/6] Compose validation"
docker compose config --quiet
SYNC_DATABASE_URL=postgresql+psycopg2://check:check@100.64.0.1:5433/check \
REDIS_URL=redis://:check@100.64.0.1:6380/0 API_BASE_URL=http://100.64.0.1:8000 \
WORKER_SECRET=check docker compose -f docker-compose.worker.yml config --quiet
DB_PASSWORD=check REDIS_PASSWORD=check TAILSCALE_IP=127.0.0.1 DOMAIN=emotionflow.site \
JWT_SECRET_KEY=check GOOGLE_MEET_PROJECT_NUMBER=123456789012 \
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet

echo "[4/6] No external inference implementation remains"
if rg -n -i "google-generativeai|google\.genai" app frontend docs requirements*.txt docker-compose*.yml; then
  echo "External inference reference found" >&2
  exit 1
fi

echo "[5/6] Local API dependencies"
docker compose up -d postgres redis api
curl --retry 10 --retry-delay 1 --retry-all-errors -fsS http://127.0.0.1:8000/health
echo

echo "[6/6] Static gate passed"
echo "NEXT: verify live_workers_ready=1 on the deployed VPS, then run the 30-second live rehearsal."
