from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import secrets

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)
from app.core.config import get_settings
from app.models.user import User
from app.models.schemas import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh,
    UserResponse, UserUpdate, ErrorResponse, MessageResponse,
    GoogleAuthRequest,
)
from app.services.email_service import (
    send_verification_email, decode_verification_token,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check existing email
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Check existing username
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        email=data.email,
        username=data.username,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Send verification email (best-effort, don't block registration)
    await send_verification_email(user.email, user.id, user.username)

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower().strip()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified. Please check your inbox.",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
)
async def refresh_token(data: TokenRefresh, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — expected refresh token",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.email and data.email != user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = data.email

    if data.full_name is not None:
        user.full_name = data.full_name

    await db.commit()
    await db.refresh(user)
    return user


# ─── Email Verification ──────────────────────────────────────────

@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    user_id = decode_verification_token(token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_verified:
        return MessageResponse(message="Email already verified")

    user.is_verified = True
    await db.commit()
    return MessageResponse(message="Email verified successfully")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(user: User = Depends(get_current_user)):
    if user.is_verified:
        return MessageResponse(message="Email already verified")

    sent = await send_verification_email(user.email, user.id, user.username)
    if not sent:
        raise HTTPException(status_code=503, detail="Failed to send verification email")

    return MessageResponse(message="Verification email sent")


# ─── Google OAuth ─────────────────────────────────────────────────

GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


@router.post("/google", response_model=TokenResponse)
async def google_auth(data: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate or register with a Google ID token (from Sign In With Google)."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    # Verify the Google ID token
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_TOKEN_INFO_URL,
            params={"id_token": data.credential},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    info = resp.json()

    # Verify audience matches our client ID
    if info.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")

    google_id = info.get("sub")
    email = info.get("email", "").lower().strip()
    name = info.get("name", "")

    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Check if user exists by google_id
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        # Check if email already registered (link accounts)
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            # Link Google ID to existing account
            user.google_id = google_id
            user.is_verified = True
        else:
            # Create new user
            username = email.split("@")[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while True:
                existing = await db.execute(select(User).where(User.username == username))
                if not existing.scalar_one_or_none():
                    break
                username = f"{base_username}{counter}"
                counter += 1

            user = User(
                email=email,
                username=username,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                full_name=name or None,
                google_id=google_id,
                is_verified=True,
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
