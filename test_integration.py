"""
Integration test suite for EmotionFlow API.
Tests auth flow, user management, analysis pipeline, API keys, admin, and telemetry.
"""
import httpx
import json
import time
import sys
import os

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
RESULTS = []


def report(name, passed, detail=""):
    global PASS, FAIL
    status = "PASS" if passed else "FAIL"
    if passed:
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append((name, status, detail))
    icon = "\u2705" if passed else "\u274c"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))


def main():
    global PASS, FAIL
    client = httpx.Client(base_url=BASE, timeout=30.0)
    tokens = {}
    admin_tokens = {}

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 1. HEALTH CHECK ===\033[0m")
    r = client.get("/health")
    report("GET /health returns 200", r.status_code == 200)
    data = r.json()
    report("Database healthy", data.get("database") == "ok")
    report("Redis healthy", data.get("redis") == "ok")

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 2. USER REGISTRATION ===\033[0m")

    # Register a normal user
    r = client.post("/auth/register", json={
        "email": "testuser@example.com",
        "username": "testuser",
        "password": "TestPass123",
        "full_name": "Test User",
    })
    report("Register user (201)", r.status_code == 201, f"status={r.status_code} body={r.text[:100]}")
    if r.status_code != 201:
        print(f"    FATAL: Registration failed. Cannot continue. Body: {r.text[:300]}")
        sys.exit(1)
    user_data = r.json()
    report("User has correct email", user_data.get("email") == "testuser@example.com")
    report("User role is 'user'", user_data.get("role") == "user")
    report("Quota limit set", user_data.get("quota_limit") == 100)

    # Duplicate email
    r = client.post("/auth/register", json={
        "email": "testuser@example.com",
        "username": "another",
        "password": "TestPass123",
    })
    report("Duplicate email rejected (409)", r.status_code == 409)

    # Duplicate username
    r = client.post("/auth/register", json={
        "email": "another@example.com",
        "username": "testuser",
        "password": "TestPass123",
    })
    report("Duplicate username rejected (409)", r.status_code == 409)

    # Weak password
    r = client.post("/auth/register", json={
        "email": "weak@example.com",
        "username": "weakuser",
        "password": "weak",
    })
    report("Weak password rejected (422)", r.status_code == 422)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 3. LOGIN & JWT ===\033[0m")

    r = client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
    })
    report("Login success (200)", r.status_code == 200)
    tokens = r.json()
    report("Access token present", "access_token" in tokens)
    report("Refresh token present", "refresh_token" in tokens)
    report("Token type is bearer", tokens.get("token_type") == "bearer")

    # Wrong password
    r = client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "WrongPass999",
    })
    report("Wrong password rejected (401)", r.status_code == 401)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 4. AUTHENTICATED ENDPOINTS ===\033[0m")

    auth_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.get("/auth/me", headers=auth_headers)
    report("GET /auth/me (200)", r.status_code == 200)
    me = r.json()
    report("Correct username", me.get("username") == "testuser")

    # Update profile
    r = client.patch("/auth/me", headers=auth_headers, json={"full_name": "Updated Name"})
    report("PATCH /auth/me (200)", r.status_code == 200)
    report("Name updated", r.json().get("full_name") == "Updated Name")

    # Unauthenticated access (HTTPBearer returns 401 when no credentials)
    r = client.get("/auth/me")
    report("Unauthenticated rejected (401)", r.status_code == 401)

    # Bad token
    r = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    report("Bad token rejected (401)", r.status_code == 401)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 5. TOKEN REFRESH ===\033[0m")

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    report("Token refresh (200)", r.status_code == 200)
    new_tokens = r.json()
    report("New access token", "access_token" in new_tokens)

    # Use new token
    auth_headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
    r = client.get("/auth/me", headers=auth_headers)
    report("New token works", r.status_code == 200)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 6. API KEY MANAGEMENT ===\033[0m")

    r = client.post("/api-keys/", headers=auth_headers, json={"name": "Test Key"})
    report("Create API key (201)", r.status_code == 201)
    key_data = r.json()
    report("Raw key returned", "raw_key" in key_data)
    report("Key prefix present", len(key_data.get("key_prefix", "")) > 0)
    report("Key name correct", key_data.get("name") == "Test Key")

    r = client.get("/api-keys/", headers=auth_headers)
    report("List API keys (200)", r.status_code == 200)
    keys = r.json()
    report("Has 1 key", len(keys) == 1)

    # Delete key
    key_id = keys[0]["id"]
    r = client.delete(f"/api-keys/{key_id}", headers=auth_headers)
    report("Delete API key (204)", r.status_code == 204)

    r = client.get("/api-keys/", headers=auth_headers)
    report("Key deleted (0 keys)", len(r.json()) == 0)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 7. FILE ANALYSIS ===\033[0m")

    # Create a fake WAV file (just needs the extension for the stub)
    fake_audio = b"RIFF" + b"\x00" * 100  # minimal WAV-like header
    files = {"file": ("test_audio.wav", fake_audio, "audio/wav")}
    r = client.post("/analysis/analyze-file", headers=auth_headers, files=files, params={"model_tier": "fast"})
    report("Submit analysis (202)", r.status_code == 202, f"status={r.status_code}")
    if r.status_code != 202:
        print(f"    Analysis failed: {r.text[:300]}")
        job_id = ""
    else:
        job = r.json()
        job_id = job.get("job_id", "")
    report("Job ID returned", len(job_id) > 0)
    report("Status is pending", job.get("status") == "pending")

    # Check job status
    r = client.get(f"/analysis/jobs/{job_id}", headers=auth_headers)
    report("Get job status (200)", r.status_code == 200)
    report("Job status pending/processing", r.json().get("status") in ["pending", "processing"])

    # List jobs
    r = client.get("/analysis/jobs", headers=auth_headers)
    report("List jobs (200)", r.status_code == 200)
    report("Has at least 1 job", len(r.json()) >= 1)

    # Unsupported file type
    files_bad = {"file": ("test.txt", b"not audio", "text/plain")}
    r = client.post("/analysis/analyze-file", headers=auth_headers, files=files_bad)
    report("Reject .txt file (415)", r.status_code == 415)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 8. ADMIN ENDPOINTS ===\033[0m")

    # Create an admin user directly via DB trick — register first, then we'll test denial
    r = client.post("/auth/register", json={
        "email": "admin@emotionflow.ai",
        "username": "admin",
        "password": "AdminPass123",
    })
    report("Register admin user (201)", r.status_code == 201)

    # Normal user can't access admin
    r = client.get("/admin/telemetry", headers=auth_headers)
    report("Non-admin rejected (403)", r.status_code == 403)

    # Promote to admin via SQL (in real app this would be a migration/seed)
    import asyncio
    import asyncpg

    async def promote_admin():
        conn = await asyncpg.connect(
            "postgresql://emotionflow:emotionflow_secret@localhost:5433/emotionflow"
        )
        await conn.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
        await conn.close()

    asyncio.run(promote_admin())

    # Login as admin
    r = client.post("/auth/login", json={
        "email": "admin@emotionflow.ai",
        "password": "AdminPass123",
    })
    admin_tokens = r.json()
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    r = client.get("/admin/telemetry", headers=admin_headers)
    report("Admin telemetry (200)", r.status_code == 200)
    telemetry = r.json()
    report("Has total_requests", "total_requests" in telemetry)
    report("Has total_users", telemetry.get("total_users", 0) >= 2)
    report("Has jobs stats", "jobs_completed" in telemetry)

    r = client.get("/admin/users", headers=admin_headers)
    report("Admin list users (200)", r.status_code == 200)
    users = r.json()
    report("Has 2+ users", len(users) >= 2)

    # Update quota
    test_user_id = None
    for u in users:
        if u["username"] == "testuser":
            test_user_id = u["id"]
    if test_user_id:
        r = client.patch(f"/admin/users/{test_user_id}/quota", headers=admin_headers, json={"quota_limit": 500})
        report("Update quota (200)", r.status_code == 200)
        report("New quota is 500", r.json().get("quota_limit") == 500)

    # Toggle user active
    if test_user_id:
        r = client.patch(f"/admin/users/{test_user_id}/toggle-active", headers=admin_headers)
        report("Toggle active (200)", r.status_code == 200)
        report("User now inactive", r.json().get("is_active") == False)

        # Re-activate
        r = client.patch(f"/admin/users/{test_user_id}/toggle-active", headers=admin_headers)
        report("Re-activate (200)", r.status_code == 200)
        report("User now active", r.json().get("is_active") == True)

    # Admin logs
    r = client.get("/admin/logs", headers=admin_headers)
    report("Admin logs (200)", r.status_code == 200)
    report("Logs have entries", len(r.json().get("logs", [])) > 0)

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 9. TELEMETRY VERIFICATION ===\033[0m")

    # Check that X-Process-Time-Ms header is present on non-skip paths
    # /health is in SKIP_PATHS so it won't have the header — use /auth/me instead
    r = client.get("/auth/me", headers=auth_headers)
    has_timing = "x-process-time-ms" in r.headers
    report("X-Process-Time-Ms header present", has_timing, r.headers.get("x-process-time-ms", "missing"))

    # ──────────────────────────────────────────────────
    print("\n\033[1m=== 10. OPENAPI DOCS ===\033[0m")
    r = client.get("/docs")
    report("Swagger UI available (200)", r.status_code == 200)
    r = client.get("/openapi.json")
    report("OpenAPI schema (200)", r.status_code == 200)
    schema = r.json()
    report("API title correct", schema.get("info", {}).get("title") == "EmotionFlow API")

    # ──────────────────────────────────────────────────
    print("\n" + "=" * 55)
    total = PASS + FAIL
    print(f"\033[1m  RESULTS: {PASS}/{total} passed, {FAIL} failed\033[0m")
    print("=" * 55)

    if FAIL > 0:
        print("\n  Failed tests:")
        for name, status, detail in RESULTS:
            if status == "FAIL":
                print(f"    \u274c {name}: {detail}")

    print()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
