from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
import re


# ─── Auth Schemas ────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: str = Field(..., max_length=255)
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v.lower().strip()

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, hyphens, and underscores")
        return v.strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefresh(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    is_verified: bool = False
    quota_limit: int
    quota_used_today: int
    created_at: datetime

    model_config = {"from_attributes": True}


class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from frontend


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v.lower().strip()


class MessageResponse(BaseModel):
    message: str


# ─── API Key Schemas ─────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    name: str = Field(default="Default Key", max_length=100)


class APIKeyResponse(BaseModel):
    id: int
    key_prefix: str
    name: str
    is_active: bool
    usage_count: int
    last_used_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyCreated(APIKeyResponse):
    """Returned only on creation — includes the full key (shown once)."""
    raw_key: str


# ─── Analysis Schemas ────────────────────────────────────────────

class EmotionShift(BaseModel):
    timestamp_start: float
    timestamp_end: float
    emotion: str
    intensity: float = Field(ge=0.0, le=1.0)
    trigger_phrase: Optional[str] = None
    cause: Optional[str] = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class EmotionTransition(BaseModel):
    from_segment: int
    to_segment: int
    from_emotion: str
    to_emotion: str
    explanation: str


class AnalysisResult(BaseModel):
    filename: str
    duration_seconds: float
    overall_sentiment: str
    summary: Optional[str] = None
    timeline: list[EmotionShift]
    transcript: list[TranscriptSegment]
    transitions: list[EmotionTransition] = []
    model_tier: str
    processing_time_ms: float


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    model_tier: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    processing_time_ms: Optional[float] = None
    result: Optional[AnalysisResult] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── Telemetry / Admin Schemas ───────────────────────────────────

class TelemetrySummary(BaseModel):
    total_requests: int
    total_users: int
    active_users_today: int
    total_analysis_jobs: int
    jobs_completed: int
    jobs_failed: int
    jobs_pending: int
    avg_processing_time_ms: Optional[float]
    error_rate_percent: float
    requests_last_hour: int


class UserAdminView(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool
    quota_limit: int
    quota_used_today: int
    total_jobs: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserQuotaUpdate(BaseModel):
    quota_limit: int = Field(ge=0, le=100000)


class ErrorResponse(BaseModel):
    detail: str


# ─── Webhook Schemas ─────────────────────────────────────────────

VALID_WEBHOOK_EVENTS = {"job.completed", "job.failed", "job.processing"}


class WebhookCreate(BaseModel):
    url: str = Field(..., max_length=2048)
    name: str = Field(default="Default Webhook", max_length=100)
    events: list[str] = Field(default=["job.completed", "job.failed"])

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if not v.startswith(("https://", "http://")):
            raise ValueError("Webhook URL must start with https:// or http://")
        return v.strip()

    @field_validator("events")
    @classmethod
    def validate_events(cls, v):
        for e in v:
            if e not in VALID_WEBHOOK_EVENTS:
                raise ValueError(f"Invalid event: {e}. Valid: {VALID_WEBHOOK_EVENTS}")
        if not v:
            raise ValueError("At least one event is required")
        return v


class WebhookUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    url: Optional[str] = Field(None, max_length=2048)
    events: Optional[list[str]] = None
    is_active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if v is not None and not v.startswith(("https://", "http://")):
            raise ValueError("Webhook URL must start with https:// or http://")
        return v.strip() if v else v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v):
        if v is not None:
            for e in v:
                if e not in VALID_WEBHOOK_EVENTS:
                    raise ValueError(f"Invalid event: {e}. Valid: {VALID_WEBHOOK_EVENTS}")
        return v


class WebhookResponse(BaseModel):
    id: int
    name: str
    url: str
    events: str
    is_active: bool
    secret: Optional[str] = None  # Only populated on creation
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: int
    webhook_id: int
    job_id: str
    event_type: str
    status: str
    status_code: Optional[int]
    error_message: Optional[str]
    attempt: int
    max_attempts: int
    next_retry_at: Optional[datetime]
    created_at: datetime
    delivered_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WebhookEventPayload(BaseModel):
    """The payload POSTed to webhook URLs."""
    event: str
    job_id: str
    status: str
    timestamp: str
    data: Optional[dict] = None
