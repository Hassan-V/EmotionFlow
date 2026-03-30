"""
Webhook CRUD Router — Register, update, delete, and inspect webhooks.
"""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery
from app.models.schemas import (
    WebhookCreate, WebhookUpdate, WebhookResponse,
    WebhookDeliveryResponse,
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

MAX_WEBHOOKS_PER_USER = 10


@router.post(
    "/",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    data: WebhookCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook endpoint."""
    # Check limit
    count = await db.execute(
        select(func.count()).select_from(Webhook).where(Webhook.user_id == user.id)
    )
    if count.scalar() >= MAX_WEBHOOKS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_WEBHOOKS_PER_USER} webhooks per user",
        )

    # Generate a signing secret
    secret = secrets.token_hex(32)

    webhook = Webhook(
        user_id=user.id,
        url=data.url,
        name=data.name,
        secret=secret,
        events=",".join(data.events),
        is_active=True,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    # Return with secret (only returned on creation, like API keys)
    return webhook


@router.get("/", response_model=list[WebhookResponse])
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all webhooks for the current user."""
    result = await db.execute(
        select(Webhook)
        .where(Webhook.user_id == user.id)
        .order_by(Webhook.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific webhook."""
    webhook = await _get_user_webhook(db, webhook_id, user.id)
    return webhook


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: int,
    data: WebhookUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook's URL, events, name, or active status."""
    webhook = await _get_user_webhook(db, webhook_id, user.id)

    if data.name is not None:
        webhook.name = data.name
    if data.url is not None:
        webhook.url = data.url
    if data.events is not None:
        webhook.events = ",".join(data.events)
    if data.is_active is not None:
        webhook.is_active = data.is_active

    await db.commit()
    await db.refresh(webhook)
    return webhook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook and all its delivery logs."""
    webhook = await _get_user_webhook(db, webhook_id, user.id)
    await db.delete(webhook)
    await db.commit()


@router.get(
    "/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
)
async def list_deliveries(
    webhook_id: int,
    status_filter: str = Query(default=None, pattern="^(pending|delivered|failed)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List delivery attempts for a webhook (most recent first)."""
    # Verify ownership
    await _get_user_webhook(db, webhook_id, user.id)

    query = (
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        query = query.where(WebhookDelivery.status == status_filter)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{webhook_id}/test", status_code=status.HTTP_200_OK)
async def test_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test event to the webhook URL."""
    from app.services.webhook_service import deliver_webhook
    from datetime import datetime, timezone

    webhook = await _get_user_webhook(db, webhook_id, user.id)

    result = await deliver_webhook(
        url=webhook.url,
        secret=webhook.secret,
        event_type="webhook.test",
        job_id="test-00000000-0000-0000-0000-000000000000",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"message": "This is a test webhook from EmotionFlow"},
    )

    return {
        "success": result["success"],
        "status_code": result["status_code"],
        "error": result.get("error"),
    }


async def _get_user_webhook(db: AsyncSession, webhook_id: int, user_id: int) -> Webhook:
    """Fetch a webhook, ensuring it belongs to the user."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user_id)
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )
    return webhook
