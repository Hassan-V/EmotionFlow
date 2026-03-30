# Authentication & Authorization

## Overview

EmotionFlow supports two authentication mechanisms:

| Mechanism | Header | Use case |
|---|---|---|
| JWT Bearer | `Authorization: Bearer <token>` | Interactive / browser clients |
| API Key | `X-API-Key: ef_<key>` | Server-to-server, automation, SaaS integration |

Both paths resolve to the same `User` object and flow through the same rate limiting and
telemetry middleware.

---

## JWT Authentication

### Registration

```
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "username": "alice",
  "password": "Password1",
  "full_name": "Alice Example"   // optional
}
```

Password rules (enforced by Pydantic validator):
- Minimum 8 characters, maximum 128
- At least one uppercase letter
- At least one lowercase letter
- At least one digit

Response `201 Created`:
```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "alice",
  "full_name": "Alice Example",
  "role": "user",
  "is_active": true,
  "quota_limit": 100,
  "quota_used_today": 0,
  "created_at": "2025-01-01T00:00:00Z"
}
```

### Login

```
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "Password1"
}
```

Response `200 OK`:
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### Token Refresh

Access tokens expire after 30 minutes. Use the refresh token (valid 7 days) to get new tokens:

```
POST /auth/refresh
Content-Type: application/json

{
  "refresh_token": "<refresh_jwt>"
}
```

### Profile

```
GET /auth/me
Authorization: Bearer <access_token>
```

---

## JWT Internals

Tokens are HS256 signed with `JWT_SECRET_KEY` from `.env`.

Access token payload:
```json
{
  "sub": "1",        // user ID as string
  "exp": 1234567890, // Unix timestamp
  "type": "access"
}
```

`get_current_user` (in `app/core/security.py`):
1. Decodes and validates the token.
2. Checks `type == "access"`.
3. Loads the user from PostgreSQL.
4. Verifies `user.is_active`.
5. Sets `request.state.user_id` so telemetry middleware can tag the log entry.

---

## API Key Authentication

### Creating an API Key

First obtain a JWT token, then:

```
POST /api-keys/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "My production key"
}
```

Response `201 Created`:
```json
{
  "id": 1,
  "key_prefix": "ef_abc123",
  "name": "My production key",
  "is_active": true,
  "last_used_at": null,
  "created_at": "2025-01-01T00:00:00Z",
  "raw_key": "ef_<44-char base64url>"
}
```

> **Important**: `raw_key` is shown **only once**. Store it securely. If lost, the key must be
> revoked and a new one created.

### Using an API Key

Pass the raw key in the `X-API-Key` header — no JWT required:

```
POST /analysis/analyze-file
X-API-Key: ef_abc123def456...
```

The API verifies the key by bcrypt-comparing against the stored hash, updates `last_used_at`
and increments `usage_count` on the `APIKey` row. No session token is needed.

### Listing Keys

```
GET /api-keys/
Authorization: Bearer <access_token>
```

Returns all keys (without the raw value):
```json
[
  {
    "id": 1,
    "key_prefix": "ef_abc123",
    "name": "My production key",
    "is_active": true,
    "usage_count": 142,
    "last_used_at": "2025-01-15T10:30:00Z",
    "created_at": "2025-01-01T00:00:00Z"
  }
]
```

`usage_count` is incremented on every authenticated API request made with that key.

### Revoking a Key

```
DELETE /api-keys/{key_id}
Authorization: Bearer <access_token>
```

Response: `204 No Content`

---

## Authorization Levels

| Role | Access |
|---|---|
| `user` | Own jobs, own webhooks, own API keys |
| `admin` | All user endpoints + `/admin/*` endpoints |

Admin routes use `Depends(get_current_admin)` which wraps `get_current_user` and adds a
role check. A non-admin gets `403 Forbidden` — no internal detail is leaked.

---

## Password Storage

Passwords are hashed with **bcrypt** (passlib, default rounds ~12). The same `hash_password`/
`verify_password` functions are reused for API key storage — the raw key is never persisted.

---

## Security Notes

- Refresh tokens are not stored server-side (stateless JWT). To revoke a session, the secret
  key must be rotated — or a deny-list added (not currently implemented).
- API keys expire only by manual revocation or when `expires_at` (optional field) is set.
- The `key_prefix` (first 10 chars, e.g. `ef_abc123`) is stored in plaintext for key
  identification in UIs — it cannot be used to authenticate.
