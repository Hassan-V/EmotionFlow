import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
import resend

from app.core.config import get_settings

logger = logging.getLogger("emotionflow.email")
settings = get_settings()


def _init_resend():
    resend.api_key = settings.RESEND_API_KEY


def create_verification_token(user_id: int) -> str:
    """Create a short-lived JWT for email verification (24h)."""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode(
        {"sub": str(user_id), "type": "email_verify", "exp": expire},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_verification_token(token: str) -> int | None:
    """Decode an email verification token. Returns user_id or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "email_verify":
            return None
        return int(payload["sub"])
    except Exception:
        return None


async def send_verification_email(to_email: str, user_id: int, username: str) -> bool:
    """Send a verification email via Resend."""
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping verification email")
        return False

    _init_resend()
    token = create_verification_token(user_id)
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [to_email],
            "subject": "Verify your EmotionFlow account",
            "html": f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
                <h2 style="color: #e4e4e7;">Welcome to EmotionFlow, {username}!</h2>
                <p style="color: #a1a1aa;">Click the button below to verify your email address.</p>
                <a href="{verify_url}"
                   style="display: inline-block; background: #7c3aed; color: white; padding: 12px 24px;
                          border-radius: 8px; text-decoration: none; font-weight: 500; margin: 20px 0;">
                    Verify Email
                </a>
                <p style="color: #71717a; font-size: 13px;">
                    Or copy this link: {verify_url}
                </p>
                <p style="color: #52525b; font-size: 12px; margin-top: 32px;">
                    This link expires in 24 hours. If you didn&rsquo;t create an account, ignore this email.
                </p>
            </div>
            """,
        })
        logger.info(f"Verification email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        return False
