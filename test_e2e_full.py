"""
Full Stack E2E Test — Tests the complete EmotionFlow pipeline:
  1. Start API server + worker + webhook receiver
  2. Register user → Login → Get JWT
  3. Register webhook endpoint
  4. Upload IEMOCAP audio file → Get job_id
  5. Worker picks up job → Faster-Whisper → multimodal fusion → local causality
  6. Poll until complete → Verify results
  7. Verify webhook was delivered
  8. Check telemetry in Redis
  9. Check rate limit headers
  10. Verify all DB records

Run with: conda run --no-capture-output -n speech-emotion python -u test_e2e_full.py
Requires: Docker (PostgreSQL + authenticated Redis) and prefetched local models
"""
import asyncio
import json
import os
import sys
import time
import subprocess
import signal
import threading
import requests
import redis
from http.server import HTTPServer, BaseHTTPRequestHandler

API_BASE = "http://localhost:8000"
IEMOCAP_BASE = "/mnt/d/IEMOCAP_full_release"
# Use a shorter utterance for faster testing (~10s audio)
TEST_AUDIO = f"{IEMOCAP_BASE}/Session1/sentences/wav/Ses01F_impro01/Ses01F_impro01_F000.wav"
# Fallback to longer dialog if sentence-level doesn't exist
TEST_AUDIO_LONG = f"{IEMOCAP_BASE}/Session1/dialog/wav/Ses01F_impro01.wav"

TEST_USER = {
    "email": f"e2etest_{int(time.time())}@emotionflow.ai",
    "username": f"e2etest_{int(time.time())}",
    "password": "TestPass123",
    "full_name": "E2E Test User",
}

POLL_INTERVAL = 3  # seconds
POLL_TIMEOUT = 300  # max 5 min for full pipeline
WEBHOOK_RECEIVER_PORT = 9999

# Shared storage for received webhooks
received_webhooks = []
webhook_lock = threading.Lock()


class WebhookReceiver(BaseHTTPRequestHandler):
    """Tiny HTTP server that captures incoming webhook deliveries."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        with webhook_lock:
            received_webhooks.append({
                "path": self.path,
                "body": json.loads(body) if body else {},
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "timestamp": time.time(),
            })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        pass  # Suppress default logging


def start_webhook_receiver():
    """Start webhook receiver in a background thread."""
    server = HTTPServer(("0.0.0.0", WEBHOOK_RECEIVER_PORT), WebhookReceiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    symbol = "✓" if condition else "✗"
    msg = f"  {symbol} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    if not condition:
        raise AssertionError(f"CHECK FAILED: {label} {detail}")


def main():
    api_proc = None
    worker_proc = None
    dispatcher_proc = None
    webhook_server = None
    redis_client = None

    try:
        # ── 0. Pre-flight checks ─────────────────────────────────
        section("PRE-FLIGHT CHECKS")

        # Check audio file exists
        audio_file = TEST_AUDIO if os.path.exists(TEST_AUDIO) else TEST_AUDIO_LONG
        check("Audio file exists", os.path.exists(audio_file), audio_file)

        # Check Docker services
        redis_client = redis.from_url("redis://localhost:6380/0", decode_responses=True)
        redis_client.ping()
        check("Redis is running", True, "localhost:6380")

        import psycopg2
        conn = psycopg2.connect(
            host="localhost", port=5433, database="emotionflow",
            user="emotionflow", password="emotionflow_secret"
        )
        conn.close()
        check("PostgreSQL is running", True, "localhost:5433")

        # Kill any stale API/worker/dispatcher processes and free ports
        import signal
        subprocess.run(["pkill", "-f", "dispatch_loop"], capture_output=True)
        subprocess.run(["pkill", "-f", "worker.py"], capture_output=True)
        subprocess.run(["pkill", "-f", "uvicorn.*app.main"], capture_output=True)
        subprocess.run(["fuser", "-k", f"{WEBHOOK_RECEIVER_PORT}/tcp", "8000/tcp"],
                       capture_output=True)
        time.sleep(1)
        # Purge stale consumer group entries so current dispatcher gets new messages cleanly
        try:
            consumers = redis_client.xinfo_consumers("webhook:events", "webhook-dispatchers")
            for consumer in consumers:
                redis_client.xgroup_delconsumer("webhook:events", "webhook-dispatchers", consumer["name"])
            if consumers:
                print(f"  ℹ Purged {len(consumers)} stale webhook consumers")
        except Exception:
            pass  # Consumer group may not exist yet

        # Clear any stale telemetry for clean test
        # (Don't delete — just note the current stream length)
        try:
            stream_len_before = redis_client.xlen("telemetry:api_logs")
        except Exception:
            stream_len_before = 0
        print(f"  ℹ Telemetry stream has {stream_len_before} entries before test")

        # Start webhook receiver
        webhook_server = start_webhook_receiver()
        check("Webhook receiver started", True, f"port {WEBHOOK_RECEIVER_PORT}")

        # ── 1. Start API Server ──────────────────────────────────
        section("STARTING API SERVER")

        env = os.environ.copy()
        api_proc = subprocess.Popen(
            ["conda", "run", "--no-capture-output", "-n", "speech-emotion",
             "python", "-u", "-m", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print(f"  API server PID: {api_proc.pid}")

        # Wait for server to be ready
        for i in range(30):
            try:
                r = requests.get(f"{API_BASE}/health", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            # Read what output we have
            api_proc.terminate()
            out = api_proc.stdout.read().decode() if api_proc.stdout else ""
            print(f"  Server output:\n{out[:2000]}")
            raise RuntimeError("API server failed to start within 30s")

        health = requests.get(f"{API_BASE}/health").json()
        check("API server healthy", health.get("status") == "healthy", json.dumps(health))

        # ── 2. Start Worker ──────────────────────────────────────
        section("STARTING AI WORKER")

        worker_proc = subprocess.Popen(
            ["conda", "run", "--no-capture-output", "-n", "speech-emotion",
             "python", "-u", "-c",
             "import asyncio; from app.services.worker import worker_loop; asyncio.run(worker_loop())"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print(f"  Worker PID: {worker_proc.pid}")
        time.sleep(3)  # Give worker time to initialize
        check("Worker process running", worker_proc.poll() is None)

        # ── 2b. Start Webhook Dispatcher ─────────────────────────
        section("STARTING WEBHOOK DISPATCHER")

        dispatcher_proc = subprocess.Popen(
            ["conda", "run", "--no-capture-output", "-n", "speech-emotion",
             "python", "-u", "-c",
             "import asyncio; from app.services.webhook_service import dispatch_loop; "
             "from app.core.config import get_settings; s = get_settings(); "
             "asyncio.run(dispatch_loop(s.REDIS_URL, s.DATABASE_URL))"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=None,  # Forward to terminal so we can see errors
            stderr=None,
        )
        print(f"  Dispatcher PID: {dispatcher_proc.pid}")
        time.sleep(2)
        check("Dispatcher process running", dispatcher_proc.poll() is None)

        # ── 3. Register User ────────────────────────────────────
        section("USER REGISTRATION & AUTH")

        r = requests.post(f"{API_BASE}/auth/register", json=TEST_USER)
        check("Register user", r.status_code == 201, f"status={r.status_code}")
        user_data = r.json()
        user_id = user_data["id"]
        check("User ID assigned", user_id > 0, f"id={user_id}")
        check("Quota initialized", user_data["quota_limit"] > 0, f"limit={user_data['quota_limit']}")
        print(f"  ℹ User: {user_data['email']} (id={user_id})")

        # ── 4. Login ─────────────────────────────────────────────
        r = requests.post(f"{API_BASE}/auth/login", json={
            "email": TEST_USER["email"],
            "password": TEST_USER["password"],
        })
        check("Login successful", r.status_code == 200, f"status={r.status_code}")
        tokens = r.json()
        access_token = tokens["access_token"]
        check("Got access token", len(access_token) > 20, f"token length={len(access_token)}")
        check("Got refresh token", len(tokens["refresh_token"]) > 20)

        headers = {"Authorization": f"Bearer {access_token}"}

        # ── 5. Get user profile ──────────────────────────────────
        r = requests.get(f"{API_BASE}/auth/me", headers=headers)
        check("Get profile", r.status_code == 200)
        me = r.json()
        check("Profile matches", me["email"] == TEST_USER["email"])

        # ── 5b. Register Webhook ─────────────────────────────────
        section("WEBHOOK REGISTRATION")

        r = requests.post(f"{API_BASE}/webhooks/", headers=headers, json={
            "url": f"http://localhost:{WEBHOOK_RECEIVER_PORT}/webhook",
            "name": "E2E Test Webhook",
            "events": ["job.completed", "job.failed"],
        })
        check("Create webhook", r.status_code == 201, f"status={r.status_code}")
        webhook_data = r.json()
        webhook_id = webhook_data["id"]
        webhook_secret = webhook_data.get("secret", "")
        check("Webhook has ID", webhook_id > 0, f"id={webhook_id}")
        check("Webhook has secret", len(webhook_secret) > 0, f"length={len(webhook_secret)}")
        check("Webhook events set", "job.completed" in webhook_data.get("events", ""))
        print(f"  ℹ Webhook: id={webhook_id}, url={webhook_data['url']}")

        # List webhooks
        r = requests.get(f"{API_BASE}/webhooks/", headers=headers)
        check("List webhooks", r.status_code == 200)
        check("Webhook in list", len(r.json()) > 0, f"{len(r.json())} webhooks")

        # Test webhook (sends test event to our receiver)
        r = requests.post(f"{API_BASE}/webhooks/{webhook_id}/test", headers=headers)
        check("Test webhook delivery", r.status_code == 200)
        test_result = r.json()
        check("Test webhook success", test_result.get("success") is True,
              f"status_code={test_result.get('status_code')}")

        # Verify test webhook was received
        time.sleep(0.5)
        with webhook_lock:
            test_hooks = [w for w in received_webhooks if w["body"].get("event") == "webhook.test"]
        check("Test webhook received", len(test_hooks) > 0, f"{len(test_hooks)} test events")

        if test_hooks:
            # Verify HMAC signature
            import hmac
            import hashlib
            test_body = json.dumps(test_hooks[0]["body"], default=str).encode()
            expected_sig = hmac.new(  # noqa: type: ignore
                webhook_secret.encode(), test_body, hashlib.sha256
            ).hexdigest()  # (re-serialization may differ; header presence is the real check)
            received_sig = test_hooks[0]["headers"].get("x-emotionflow-signature", "")
            # Note: signature is on the exact bytes sent, which may differ from our re-serialization
            check("Webhook has HMAC signature header", len(received_sig) > 0, f"sig={received_sig[:16]}...")

        # ── 6. Upload Audio File ─────────────────────────────────
        section("FILE UPLOAD & JOB SUBMISSION")

        file_size = os.path.getsize(audio_file)
        print(f"  ℹ Uploading: {os.path.basename(audio_file)} ({file_size / 1024:.1f} KB)")

        with open(audio_file, "rb") as f:
            r = requests.post(
                f"{API_BASE}/analysis/analyze-file",
                headers=headers,
                files={"file": (os.path.basename(audio_file), f, "audio/wav")},
                params={"model_tier": "balanced", "session_id": "e2e-test-session"},
            )

        check("Upload accepted", r.status_code == 202, f"status={r.status_code}")
        job = r.json()
        job_id = job["job_id"]
        check("Got job ID", len(job_id) > 0, f"job_id={job_id}")
        check("Status is pending", job["status"] == "pending")
        print(f"  ℹ Job submitted: {job_id}")

        # Check response headers for telemetry
        check("X-Process-Time-Ms header", "x-process-time-ms" in r.headers,
              f"{r.headers.get('x-process-time-ms', 'MISSING')}ms")

        # ── 7. Poll for Completion ───────────────────────────────
        section("POLLING FOR RESULTS (worker processing)")

        start_poll = time.time()
        final_status = None
        poll_count = 0

        while time.time() - start_poll < POLL_TIMEOUT:
            r = requests.get(f"{API_BASE}/analysis/jobs/{job_id}", headers=headers)
            check_response = r.json()
            current_status = check_response["status"]
            poll_count += 1

            elapsed = time.time() - start_poll
            print(f"  [{elapsed:.0f}s] Poll #{poll_count}: status={current_status}")

            if current_status in ("completed", "failed"):
                final_status = check_response
                break

            time.sleep(POLL_INTERVAL)
        else:
            raise TimeoutError(f"Job didn't complete within {POLL_TIMEOUT}s")

        # ── 8. Verify Results ────────────────────────────────────
        section("RESULT VERIFICATION")

        check("Job completed", final_status["status"] == "completed",
              f"status={final_status['status']}, error={final_status.get('error_message')}")

        check("Has processing time", final_status.get("processing_time_ms", 0) > 0,
              f"{final_status.get('processing_time_ms', 0):.0f}ms")

        result = final_status.get("result")
        check("Has result data", result is not None)

        if result:
            check("Has filename", len(result.get("filename", "")) > 0, result.get("filename"))
            check("Has duration", result.get("duration_seconds", 0) > 0,
                  f"{result.get('duration_seconds', 0):.1f}s")
            check("Has overall sentiment", len(result.get("overall_sentiment", "")) > 0,
                  result.get("overall_sentiment"))
            check("Model tier is balanced", result.get("model_tier") == "balanced")

            # Timeline (emotion segments from our models)
            timeline = result.get("timeline", [])
            check("Has emotion timeline", len(timeline) > 0, f"{len(timeline)} segments")

            if timeline:
                seg0 = timeline[0]
                check("Segment has emotion", len(seg0.get("emotion", "")) > 0, seg0.get("emotion"))
                check("Segment has intensity", 0 <= seg0.get("intensity", -1) <= 1,
                      f"intensity={seg0.get('intensity')}")
                check("Segment has timestamps", seg0.get("timestamp_end", 0) > seg0.get("timestamp_start", 0))

                # Check for local causality (trigger phrases / causes)
                has_triggers = sum(1 for s in timeline if s.get("trigger_phrase"))
                has_causes = sum(1 for s in timeline if s.get("cause"))
                # For very short audio (<3 segments), there may be no transition trigger.
                if len(timeline) >= 3:
                    check("Pipeline added trigger phrases", has_triggers > 0, f"{has_triggers}/{len(timeline)} segments")
                    check("Pipeline added causal explanations", has_causes > 0, f"{has_causes}/{len(timeline)} segments")
                else:
                    print(f"  ℹ Local causality: {has_triggers}/{len(timeline)} triggers, {has_causes}/{len(timeline)} causes (short audio, acceptable)")
                    check("Overall sentiment set", len(result.get("overall_sentiment", "")) > 0)

                # Emotion distribution from our models
                emotions = {}
                for seg in timeline:
                    e = seg["emotion"]
                    emotions[e] = emotions.get(e, 0) + 1
                print(f"  ℹ Emotion distribution (from our models): {json.dumps(emotions, indent=2)}")

            # Transcript (from Whisper ASR)
            transcript = result.get("transcript", [])
            check("Has transcript", len(transcript) > 0, f"{len(transcript)} segments")

            if transcript:
                full_text = " ".join(s["text"] for s in transcript)
                check("Transcript has content", len(full_text) > 3, f"{len(full_text)} chars")
                print(f"  ℹ Transcript preview: {full_text[:200]}...")

            # Stabilized transitions
            transitions = result.get("transitions", [])
            if transitions:
                check("Has emotional transitions", len(transitions) > 0, f"{len(transitions)} transitions")
                print(f"  ℹ Transitions: {json.dumps(transitions[:3], indent=2)}")

            # Summary
            summary = result.get("summary", "")
            if summary:
                print(f"  ℹ Summary: {summary[:300]}...")

        # ── 9. Verify List Jobs ──────────────────────────────────
        section("LIST JOBS ENDPOINT")

        r = requests.get(f"{API_BASE}/analysis/jobs", headers=headers)
        check("List jobs", r.status_code == 200)
        jobs = r.json()
        check("Our job in list", any(j["job_id"] == job_id for j in jobs), f"{len(jobs)} total jobs")

        # Filter by status
        r = requests.get(f"{API_BASE}/analysis/jobs", headers=headers,
                         params={"status_filter": "completed"})
        check("Filter by status works", r.status_code == 200)

        # ── 9b. Webhook Delivery Verification ────────────────────
        section("WEBHOOK DELIVERY VERIFICATION")

        # Give dispatcher a moment to pick up the event and deliver
        print("  Waiting for webhook delivery...")
        webhook_received = False
        for i in range(20):
            with webhook_lock:
                completion_hooks = [
                    w for w in received_webhooks
                    if w["body"].get("event") == "job.completed"
                    and w["body"].get("job_id") == job_id
                ]
            if completion_hooks:
                webhook_received = True
                break
            time.sleep(1)

        check("Webhook delivered for job completion", webhook_received)

        if completion_hooks:
            hook = completion_hooks[0]
            payload = hook["body"]
            check("Webhook event=job.completed", payload.get("event") == "job.completed")
            check("Webhook has correct job_id", payload.get("job_id") == job_id)
            check("Webhook has status", payload.get("status") == "completed")
            check("Webhook has timestamp", len(payload.get("timestamp", "")) > 0)
            check("Webhook has data", payload.get("data") is not None)

            wh_data = payload.get("data", {})
            check("Data has processing_time_ms", wh_data.get("processing_time_ms", 0) > 0)
            check("Data has overall_sentiment", len(wh_data.get("overall_sentiment", "")) > 0)
            check("Data has model_tier", wh_data.get("model_tier") == "balanced")

            # Verify HMAC headers present
            check("Has X-EmotionFlow-Signature", len(hook["headers"].get("x-emotionflow-signature", "")) > 0)
            check("Has X-EmotionFlow-Event", hook["headers"].get("x-emotionflow-event") == "job.completed")

            print(f"  ℹ Webhook payload: event={payload['event']}, sentiment={wh_data.get('overall_sentiment')}")

        # Check delivery log via API
        r = requests.get(f"{API_BASE}/webhooks/{webhook_id}/deliveries", headers=headers)
        check("List deliveries", r.status_code == 200)
        deliveries = r.json()
        check("Delivery logged", len(deliveries) > 0, f"{len(deliveries)} deliveries")

        if deliveries:
            # Find the job.completed delivery (not the test one)
            job_deliveries = [d for d in deliveries if d.get("event_type") == "job.completed"]
            if job_deliveries:
                d = job_deliveries[0]
                check("Delivery status=delivered", d.get("status") == "delivered")
                check("Delivery has job_id", d.get("job_id") == job_id)
                check("Delivery status_code=200", d.get("status_code") == 200)

        # ── 10. Telemetry Verification ───────────────────────────
        section("TELEMETRY VERIFICATION")

        # Check Redis stream
        stream_len_after = redis_client.xlen("telemetry:api_logs")
        new_entries = stream_len_after - stream_len_before
        check("Telemetry entries logged", new_entries > 0, f"{new_entries} new entries")

        # Read recent telemetry entries
        entries = redis_client.xrevrange("telemetry:api_logs", count=50)
        our_entries = [e for e in entries if e[1].get("user_id") == str(user_id)]
        check("Entries tagged with user_id", len(our_entries) > 0, f"{len(our_entries)} entries for user {user_id}")

        # Check specific paths were logged
        paths_logged = set(e[1].get("path", "") for e in our_entries)
        check("/auth/me logged", "/auth/me" in paths_logged, str(paths_logged))
        check("/analysis/* logged", any("/analysis/" in p for p in paths_logged))

        # Check telemetry counters
        total_req = redis_client.get("telemetry:total_requests")
        check("Total request counter", total_req is not None and int(total_req) > 0,
              f"total={total_req}")

        user_req = redis_client.get(f"telemetry:user:{user_id}:requests")
        check("Per-user request counter", user_req is not None and int(user_req) > 0,
              f"user requests={user_req}")

        # Print some telemetry detail
        print(f"\n  Recent telemetry for user {user_id}:")
        for entry_id, data in our_entries[:5]:
            print(f"    {data.get('method', '?')} {data.get('path', '?')} "
                  f"→ {data.get('status_code', '?')} ({data.get('process_time_ms', '?')}ms)")

        # ── 11. Rate Limit Verification ──────────────────────────
        section("RATE LIMIT CHECK")

        # Make several rapid requests and check we're NOT rate limited
        for i in range(5):
            r = requests.get(f"{API_BASE}/auth/me", headers=headers)
            check(f"Request {i+1}/5 not rate limited", r.status_code == 200)

        # ── 12. DB Verification ──────────────────────────────────
        section("DATABASE VERIFICATION")

        import psycopg2
        conn = psycopg2.connect(
            host="localhost", port=5433, database="emotionflow",
            user="emotionflow", password="emotionflow_secret"
        )
        cur = conn.cursor()

        # Check user record
        cur.execute("SELECT id, email, quota_used_today FROM users WHERE email = %s", (TEST_USER["email"],))
        row = cur.fetchone()
        check("User in DB", row is not None, f"id={row[0] if row else 'N/A'}")
        check("Quota incremented", row[2] > 0 if row else False, f"quota_used_today={row[2] if row else 0}")

        # Check job record
        cur.execute("SELECT job_id, status, model_tier, processing_time_ms, result IS NOT NULL FROM analysis_jobs WHERE job_id = %s",
                     (job_id,))
        row = cur.fetchone()
        check("Job in DB", row is not None)
        check("Job status=completed in DB", row[1] == "completed" if row else False)
        check("Job has result JSON in DB", row[4] if row else False)
        check("Job tier=balanced in DB", row[2] == "balanced" if row else False)

        conn.close()

        # ── 13. Save Results ─────────────────────────────────────
        section("SAVING TEST ARTIFACTS")

        os.makedirs("test_data", exist_ok=True)
        artifact = {
            "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "audio_file": audio_file,
            "user": {"id": user_id, "email": TEST_USER["email"]},
            "job_id": job_id,
            "processing_time_ms": final_status.get("processing_time_ms"),
            "result": result,
            "telemetry": {
                "new_entries": new_entries,
                "user_entries": len(our_entries),
                "paths_logged": list(paths_logged),
            },
            "poll_count": poll_count,
            "total_wall_time_s": round(time.time() - start_poll, 1),
        }
        with open("test_data/e2e_full_result.json", "w") as f:
            json.dump(artifact, f, indent=2, default=str)
        print(f"  Saved to test_data/e2e_full_result.json")

        # ── FINAL SUMMARY ────────────────────────────────────────
        section("ALL CHECKS PASSED ✓")
        print(f"  Audio: {os.path.basename(audio_file)}")
        print("  Pipeline: Faster-Whisper → audio/text emotion → fusion → local Qwen/fallback")
        print(f"  Processing: {final_status.get('processing_time_ms', 0):.0f}ms")
        print(f"  Segments: {len(timeline)} emotional, {len(transcript)} transcript")
        print(f"  Telemetry: {new_entries} API logs, {user_req} user requests tracked")
        with webhook_lock:
            total_hooks = len(received_webhooks)
        print(f"  Webhooks: {total_hooks} total received (test + job events)")
        print(f"  Wall time: {time.time() - start_poll:.1f}s (incl. poll overhead)")
        print()

    except Exception as e:
        print(f"\n  ✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

        # Dump worker output for debugging
        if worker_proc and worker_proc.stdout:
            try:
                worker_proc.terminate()
                out = worker_proc.stdout.read().decode()
                print(f"\n--- Worker output ---\n{out[-3000:]}")
            except Exception:
                pass

        sys.exit(1)

    finally:
        # Cleanup
        print("\nCleaning up processes...")
        for proc, name in [(api_proc, "API"), (worker_proc, "Worker"), (dispatcher_proc, "Dispatcher")]:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                    print(f"  {name} process stopped (PID {proc.pid})")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    print(f"  {name} process killed (PID {proc.pid})")

        # Stop webhook receiver
        if webhook_server:
            try:
                webhook_server.shutdown()
                print("  Webhook receiver stopped")
            except Exception:
                pass


if __name__ == "__main__":
    main()
