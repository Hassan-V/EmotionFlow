"""
API Key + Billing End-to-End Test
==================================
Tests the complete metering / billing flow:

  1.  Start API server, worker, and webhook dispatcher as subprocesses
  2.  Register a test user
  3.  Log in → get JWT
  4.  Create an API key
  5.  Submit an analysis job using ONLY the API key (no JWT)
  6.  Poll until the job completes
  7.  Verify:
        a) The job's api_key_id is set in PostgreSQL
        b) APIKey.usage_count was incremented
        c) APIKey.last_used_at was updated
        d) A BillingEvent row was written for the job
        e) Telemetry logs show the user_id tag (API key auth path)
        f) GET /admin/billing/summary shows the user + cost
        g) GET /api-keys/ shows the updated usage_count
  8.  Clean up test user

Usage:
    conda run --no-capture-output -n speech-emotion python -u test_apikey_billing.py
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid

import httpx

# ── Config ───────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
AUDIO_FILE = os.path.join(
    os.path.dirname(__file__),
    "test_data",
    "short_test.wav",
)
# Fall back to IEMOCAP sample if the test file doesn't exist
IEMOCAP_FILE = (
    "/mnt/d/IEMOCAP_full_release/Session1/sentences/wav/"
    "Ses01F_impro01/Ses01F_impro01_F000.wav"
)
ADMIN_EMAIL = "admin@emotionflow.test"
ADMIN_PASSWORD = "Admin123!"

TEST_USER_SUFFIX = uuid.uuid4().hex[:8]
TEST_EMAIL = f"billing_test_{TEST_USER_SUFFIX}@test.local"
TEST_USERNAME = f"billing_{TEST_USER_SUFFIX}"
TEST_PASSWORD = "BillingTest1!"

POLL_TIMEOUT = 180      # seconds to wait for job completion
POLL_INTERVAL = 3

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"{GREEN}✓{RESET} {msg}")


def fail(msg):
    print(f"{RED}✗ FAIL: {msg}{RESET}")
    sys.exit(1)


def header(msg):
    print(f"\n{BOLD}── {msg} ──{RESET}")


# ── Process management ───────────────────────────────────────────

def start_api():
    return subprocess.Popen(
        [
            "conda", "run", "--no-capture-output", "-n", "speech-emotion",
            "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
        ],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def start_worker():
    return subprocess.Popen(
        [
            "conda", "run", "--no-capture-output", "-n", "speech-emotion",
            "python", "-u", "-m", "app.services.worker",
        ],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def start_dispatcher():
    return subprocess.Popen(
        [
            "conda", "run", "--no-capture-output", "-n", "speech-emotion",
            "python", "-u", "-m", "app.services.webhook_service",
        ],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def wait_api_ready(max_wait=30):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def kill_proc(proc):
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# ── DB helpers (direct SQLAlchemy sync) ─────────────────────────

def get_db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.config import get_settings
    settings = get_settings()
    engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
    return sessionmaker(bind=engine)


def db_get_job(SessionLocal, job_id: str):
    from app.models.analysis import AnalysisJob
    with SessionLocal() as db:
        return db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()


def db_get_api_key(SessionLocal, key_id: int):
    from app.models.user import APIKey
    with SessionLocal() as db:
        return db.query(APIKey).filter(APIKey.id == key_id).first()


def db_get_billing_event(SessionLocal, job_id: str):
    from app.models.billing import BillingEvent
    with SessionLocal() as db:
        return db.query(BillingEvent).filter(BillingEvent.job_id == job_id).first()


def db_delete_user(SessionLocal, user_id: int):
    from app.models.user import User
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            db.delete(user)
            db.commit()


# ── Redis helpers ────────────────────────────────────────────────

def redis_check_user_tagged(user_id: int) -> bool:
    import redis as _redis
    from app.core.config import get_settings
    settings = get_settings()
    r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
    entries = r.xrevrange("telemetry:api_logs", count=50)
    for _, data in entries:
        if data.get("user_id") == str(user_id):
            return True
    return False


# ── Pre-flight: kill stale processes ─────────────────────────────

def preflight_cleanup():
    header("Pre-flight cleanup")
    subprocess.run(
        ["pkill", "-f", "uvicorn app.main:app"],
        capture_output=True,
    )
    subprocess.run(
        ["pkill", "-f", "app.services.worker"],
        capture_output=True,
    )
    subprocess.run(
        ["pkill", "-f", "app.services.webhook_service"],
        capture_output=True,
    )
    time.sleep(2)
    ok("Stale processes cleared")


# ── Main test ────────────────────────────────────────────────────

def main():
    # Import models here (after sys.path is set)
    sys.path.insert(0, os.path.dirname(__file__))
    from app.models.analysis import AnalysisJob  # noqa — pre-load mapper
    from app.models.user import User, APIKey  # noqa
    from app.models.billing import BillingEvent  # noqa
    from app.models.webhook import Webhook, WebhookDelivery  # noqa

    preflight_cleanup()
    SessionLocal = get_db_session()

    audio = AUDIO_FILE if os.path.exists(AUDIO_FILE) else IEMOCAP_FILE
    if not os.path.exists(audio):
        fail(f"No test audio file found at {audio}")

    processes = []
    try:
        # ── Step 1: Start services ────────────────────────────────
        header("Starting services")
        api_proc = start_api()
        processes.append(api_proc)
        time.sleep(2)
        worker_proc = start_worker()
        processes.append(worker_proc)

        if not wait_api_ready(30):
            fail("API did not become ready in 30s")
        ok("API server ready")

        # ── Step 2: Get admin token ───────────────────────────────
        header("Admin login")
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            if r.status_code != 200:
                fail(f"Admin login failed: {r.text}")
            admin_token = r.json()["access_token"]
            ok(f"Admin logged in")

        # ── Step 3: Register test user ────────────────────────────
        header("Register test user")
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.post("/auth/register", json={
                "email": TEST_EMAIL,
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
            })
            if r.status_code != 201:
                fail(f"Registration failed: {r.text}")
            user_data = r.json()
            user_id = user_data["id"]
            ok(f"User registered: {TEST_USERNAME} (id={user_id})")

        # ── Step 4: Get user JWT ──────────────────────────────────
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.post("/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
            user_token = r.json()["access_token"]
            ok("User JWT obtained")

        # ── Step 5: Create API key ────────────────────────────────
        header("Create API key")
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.post(
                "/api-keys/",
                json={"name": "BillingTestKey"},
                headers={"Authorization": f"Bearer {user_token}"},
            )
            if r.status_code != 201:
                fail(f"API key creation failed: {r.text}")
            key_data = r.json()
            raw_key = key_data["raw_key"]
            key_id = key_data["id"]
            ok(f"API key created: {key_data['key_prefix']}... (id={key_id})")

        # ── Step 6: Submit job using API key only (no JWT) ────────
        header("Submit job via API key")
        with httpx.Client(base_url=BASE_URL, timeout=60) as client:
            with open(audio, "rb") as f:
                r = client.post(
                    "/analysis/analyze-file",
                    files={"file": (os.path.basename(audio), f, "audio/wav")},
                    params={"model_tier": "fast"},
                    headers={"X-API-Key": raw_key},   # NO Bearer token
                )
            if r.status_code != 202:
                fail(f"Job submission failed: {r.text}")
            job_id = r.json()["job_id"]
            ok(f"Job submitted via API key: {job_id}")

        # ── Step 7: Poll until complete ───────────────────────────
        header("Waiting for job completion")
        start = time.time()
        completed = False
        while time.time() - start < POLL_TIMEOUT:
            with httpx.Client(base_url=BASE_URL) as client:
                r = client.get(
                    f"/analysis/jobs/{job_id}",
                    headers={"X-API-Key": raw_key},
                )
            status_val = r.json().get("status")
            elapsed = time.time() - start
            print(f"  [{elapsed:.0f}s] status={status_val}", end="\r")
            if status_val == "completed":
                completed = True
                print()
                ok(f"Job completed in {elapsed:.0f}s")
                break
            elif status_val == "failed":
                print()
                fail(f"Job failed: {r.json().get('error_message')}")
            time.sleep(POLL_INTERVAL)

        if not completed:
            fail(f"Job did not complete within {POLL_TIMEOUT}s")

        # ── Step 8: Verify DB records ─────────────────────────────
        header("Verifying DB records")

        # a) AnalysisJob.api_key_id set
        time.sleep(1)  # brief settle
        job_row = db_get_job(SessionLocal, job_id)
        if not job_row:
            fail("Job row not found in DB")
        if job_row.api_key_id != key_id:
            fail(f"Job.api_key_id={job_row.api_key_id}, expected {key_id}")
        ok(f"AnalysisJob.api_key_id = {job_row.api_key_id} ✓")

        # b) APIKey.usage_count incremented (at least once for submit + once for poll)
        key_row = db_get_api_key(SessionLocal, key_id)
        if not key_row:
            fail("APIKey row not found")
        if key_row.usage_count < 1:
            fail(f"APIKey.usage_count={key_row.usage_count}, expected ≥ 1")
        ok(f"APIKey.usage_count = {key_row.usage_count}")

        # c) APIKey.last_used_at updated
        if not key_row.last_used_at:
            fail("APIKey.last_used_at is null")
        ok(f"APIKey.last_used_at = {key_row.last_used_at}")

        # d) BillingEvent written
        billing_row = db_get_billing_event(SessionLocal, job_id)
        if not billing_row:
            fail("BillingEvent row not found for job")
        if billing_row.user_id != user_id:
            fail(f"BillingEvent.user_id={billing_row.user_id}, expected {user_id}")
        if billing_row.api_key_id != key_id:
            fail(f"BillingEvent.api_key_id={billing_row.api_key_id}, expected {key_id}")
        if billing_row.status != "completed":
            fail(f"BillingEvent.status={billing_row.status}")
        if billing_row.cost_usd <= 0:
            fail(f"BillingEvent.cost_usd={billing_row.cost_usd}, expected > 0")
        ok(f"BillingEvent: tier={billing_row.model_tier} cost=${billing_row.cost_usd:.4f} status={billing_row.status}")

        # e) Telemetry tagged with user_id
        if not redis_check_user_tagged(user_id):
            fail(f"user_id={user_id} not found in telemetry:api_logs (API key auth path)")
        ok(f"Telemetry tagged with user_id={user_id}")

        # ── Step 9: Admin billing summary ─────────────────────────
        header("Admin billing summary")
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.get(
                "/admin/billing/summary",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if r.status_code != 200:
                fail(f"Billing summary failed: {r.text}")
            billing = r.json()

        user_billing = next((u for u in billing["by_user"] if u["user_id"] == user_id), None)
        if not user_billing:
            fail(f"User {user_id} not in billing summary")
        if user_billing["jobs_completed"] < 1:
            fail(f"Expected ≥1 completed job in billing, got {user_billing['jobs_completed']}")
        ok(f"Billing: user={TEST_USERNAME} jobs={user_billing['jobs_completed']} cost=${user_billing['total_cost_usd']}")

        key_billing = next((k for k in billing["by_api_key"] if k["api_key_id"] == key_id), None)
        if not key_billing:
            fail(f"API key id={key_id} not in billing by_api_key")
        ok(f"Billing per-key: key={key_billing['key_prefix']} jobs={key_billing['jobs_this_period']} cost=${key_billing['cost_usd_this_period']}")

        # ── Step 10: Check usage_count via API ─────────────────────
        header("API key usage_count via /api-keys/")
        with httpx.Client(base_url=BASE_URL) as client:
            r = client.get(
                "/api-keys/",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            keys = r.json()
            my_key = next((k for k in keys if k["id"] == key_id), None)
            if not my_key:
                fail("Key not found in /api-keys/ list")
            ok(f"/api-keys/ reports usage_count={my_key['usage_count']} last_used_at={my_key['last_used_at']}")

        print(f"\n{GREEN}{BOLD}All checks passed.{RESET}")
        print(f"  Total cost this period: ${billing['total_cost_usd']}")
        print(f"  Tier rates: {billing['tier_rates_usd']}")

    finally:
        header("Cleanup")
        try:
            db_delete_user(SessionLocal, user_id)
            ok(f"Test user {TEST_USERNAME} deleted")
        except Exception as e:
            print(f"  (cleanup error: {e})")
        for p in processes:
            kill_proc(p)
        ok("Processes stopped")


if __name__ == "__main__":
    main()
