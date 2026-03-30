"""
Webhook Service — Event publishing + delivery with horizontal scalability.

Architecture:
  Worker → Redis Stream "webhook:events" → Dispatcher(s) → HTTP POST to user URLs

  - Workers publish events (fire-and-forget to Redis)
  - One or more dispatcher processes consume via Redis Consumer Groups
  - Each dispatcher claims events, delivers webhooks, retries on failure
  - Consumer groups = horizontal scaling with no coordination needed

HMAC-SHA256 signing:
  - Each webhook has a unique secret
  - Payload is signed: X-EmotionFlow-Signature = HMAC-SHA256(secret, body)
  - Clients verify signature to trust the webhook source
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import httpx

logger = logging.getLogger("emotionflow.webhooks")

STREAM_NAME = "webhook:events"
CONSUMER_GROUP = "webhook-dispatchers"

# Retry backoff: attempt 1→30s, 2→60s, 3→120s, 4→300s, 5→give up
RETRY_DELAYS = [30, 60, 120, 300]
DELIVERY_TIMEOUT = 10  # seconds per HTTP request


def sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload_bytes: bytes, secret: str, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature (constant-time comparison)."""
    expected = sign_payload(payload_bytes, secret)
    return hmac.compare_digest(expected, signature)


async def publish_event(
    redis_client,
    event_type: str,
    job_id: str,
    user_id: int,
    data: Optional[dict] = None,
):
    """
    Publish a webhook event to Redis Stream.
    Called by the worker when a job completes/fails.
    Non-blocking — just pushes to the stream.
    """
    event = {
        "event_type": event_type,
        "job_id": job_id,
        "user_id": str(user_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": json.dumps(data or {}),
    }
    await redis_client.xadd(STREAM_NAME, event, maxlen=10000)
    logger.info(f"Published webhook event: {event_type} for job {job_id}")


def publish_event_sync(
    redis_client,
    event_type: str,
    job_id: str,
    user_id: int,
    data: Optional[dict] = None,
):
    """Sync version for worker process (which uses sync Redis)."""
    event = {
        "event_type": event_type,
        "job_id": job_id,
        "user_id": str(user_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": json.dumps(data or {}),
    }
    redis_client.xadd(STREAM_NAME, event, maxlen=10000)
    logger.info(f"Published webhook event: {event_type} for job {job_id}")


async def deliver_webhook(
    url: str,
    secret: str,
    event_type: str,
    job_id: str,
    timestamp: str,
    data: dict,
) -> dict:
    """
    Deliver a single webhook. Returns delivery result dict.
    """
    payload = {
        "event": event_type,
        "job_id": job_id,
        "status": data.get("status", event_type.split(".")[-1]),
        "timestamp": timestamp,
        "data": data,
    }
    body = json.dumps(payload, default=str)
    body_bytes = body.encode("utf-8")
    signature = sign_payload(body_bytes, secret)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "EmotionFlow-Webhook/1.0",
        "X-EmotionFlow-Signature": signature,
        "X-EmotionFlow-Event": event_type,
        "X-EmotionFlow-Delivery-Timestamp": timestamp,
    }

    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            response = await client.post(url, content=body_bytes, headers=headers)

        return {
            "success": 200 <= response.status_code < 300,
            "status_code": response.status_code,
            "response_body": response.text[:1024],
            "error": None,
        }
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "response_body": None, "error": "Timeout"}
    except httpx.ConnectError as e:
        return {"success": False, "status_code": None, "response_body": None, "error": f"Connection failed: {e}"}
    except Exception as e:
        return {"success": False, "status_code": None, "response_body": None, "error": str(e)[:500]}


async def dispatch_loop(redis_url: str, db_url: str):
    """
    Main dispatcher loop — runs as a separate process.
    Consumes from Redis Stream via consumer group for horizontal scalability.

    Multiple instances can run simultaneously — Redis consumer groups
    ensure each event is processed by exactly one dispatcher.
    """
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, update
    from app.models.webhook import Webhook, WebhookDelivery
    # Import all models so SQLAlchemy can configure all relationship mappers
    from app.models.user import User  # noqa: F401
    from app.models.analysis import AnalysisJob  # noqa: F401

    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    engine = create_async_engine(db_url, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Generate a unique consumer name for this instance
    import socket
    import os
    consumer_name = f"dispatcher-{socket.gethostname()}-{os.getpid()}"

    # Create consumer group if it doesn't exist
    try:
        await redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"Created consumer group '{CONSUMER_GROUP}'")
    except Exception:
        pass  # Group already exists

    logger.info(f"Webhook dispatcher started: {consumer_name}")

    _idle_count = 0  # track idle cycles for periodic autoclaim

    while True:
        try:
            # Periodically reclaim stale messages from dead consumers (every 5 idle cycles ≈ 25s)
            if _idle_count % 5 == 0:
                try:
                    claimed = await redis_client.xautoclaim(
                        STREAM_NAME, CONSUMER_GROUP, consumer_name,
                        min_idle_time=15000,  # claim messages idle > 15s
                        start_id="0", count=10,
                    )
                    stale_msgs = claimed[1] if claimed and len(claimed) > 1 else []
                    if stale_msgs:
                        logger.info(f"Reclaimed {len(stale_msgs)} stale messages from dead consumers")
                        for msg_id, event_data in stale_msgs:
                            try:
                                await _handle_event(async_session, event_data)
                                await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                            except Exception as e:
                                logger.error(f"Failed to handle reclaimed event {msg_id}: {e}")
                except Exception as e:
                    logger.debug(f"xautoclaim error (non-critical): {e}")

            # Read new events from the stream (block 5s)
            results = await redis_client.xreadgroup(
                CONSUMER_GROUP, consumer_name,
                {STREAM_NAME: ">"},
                count=10, block=5000,
            )

            if not results:
                # Also check for retries while idle
                await _process_retries(async_session, redis_client)
                _idle_count += 1
                continue

            _idle_count = 0  # reset on activity

            for stream, messages in results:
                for msg_id, event_data in messages:
                    try:
                        await _handle_event(async_session, event_data)
                        # Acknowledge the message
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                    except Exception as e:
                        logger.error(f"Failed to handle event {msg_id}: {e}")
                        # Don't ack — will be re-delivered on restart

            # Periodically process retries
            await _process_retries(async_session, redis_client)

        except Exception as e:
            logger.error(f"Dispatcher loop error: {e}")
            import asyncio
            await asyncio.sleep(2)


async def _handle_event(async_session, event_data: dict):
    """Handle a single webhook event — find matching webhooks and deliver."""
    from sqlalchemy import select
    from app.models.webhook import Webhook, WebhookDelivery

    event_type = event_data.get("event_type", "")
    job_id = event_data.get("job_id", "")
    user_id = int(event_data.get("user_id", 0))
    timestamp = event_data.get("timestamp", "")
    data = json.loads(event_data.get("data", "{}"))

    if not user_id or not job_id:
        logger.warning(f"Skipping malformed event: {event_data}")
        return

    # Find all active webhooks for this user that match the event type
    async with async_session() as session:
        result = await session.execute(
            select(Webhook).where(
                Webhook.user_id == user_id,
                Webhook.is_active == True,
            )
        )
        webhooks = result.scalars().all()

    for webhook in webhooks:
        # Check if this webhook is subscribed to this event type
        subscribed_events = [e.strip() for e in webhook.events.split(",")]
        if event_type not in subscribed_events:
            continue

        # Deliver
        result = await deliver_webhook(
            url=webhook.url,
            secret=webhook.secret,
            event_type=event_type,
            job_id=job_id,
            timestamp=timestamp,
            data=data,
        )

        # Log the delivery attempt
        async with async_session() as session:
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                job_id=job_id,
                event_type=event_type,
                payload=data,
                status="delivered" if result["success"] else "pending",
                status_code=result["status_code"],
                response_body=result.get("response_body"),
                error_message=result.get("error"),
                attempt=1,
                max_attempts=5,
                delivered_at=datetime.now(timezone.utc) if result["success"] else None,
                next_retry_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=RETRY_DELAYS[0])
                    if not result["success"] else None
                ),
            )
            session.add(delivery)
            await session.commit()

        if result["success"]:
            logger.info(f"Delivered {event_type} to webhook {webhook.id} ({result['status_code']})")
        else:
            logger.warning(f"Failed to deliver {event_type} to webhook {webhook.id}: {result.get('error')}")


async def _process_retries(async_session, redis_client):
    """Process webhook deliveries that need retrying."""
    from sqlalchemy import select, update
    from app.models.webhook import Webhook, WebhookDelivery

    now = datetime.now(timezone.utc)

    async with async_session() as session:
        result = await session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_retry_at <= now,
                WebhookDelivery.attempt < WebhookDelivery.max_attempts,
            )
            .limit(20)
        )
        pending = result.scalars().all()

    for delivery in pending:
        # Load the webhook for URL + secret
        async with async_session() as session:
            wh_result = await session.execute(
                select(Webhook).where(Webhook.id == delivery.webhook_id)
            )
            webhook = wh_result.scalar_one_or_none()

        if not webhook or not webhook.is_active:
            # Mark as failed if webhook was deleted/disabled
            async with async_session() as session:
                await session.execute(
                    update(WebhookDelivery)
                    .where(WebhookDelivery.id == delivery.id)
                    .values(status="failed", error_message="Webhook disabled or deleted")
                )
                await session.commit()
            continue

        # Retry delivery
        result = await deliver_webhook(
            url=webhook.url,
            secret=webhook.secret,
            event_type=delivery.event_type,
            job_id=delivery.job_id,
            timestamp=delivery.created_at.isoformat(),
            data=delivery.payload,
        )

        new_attempt = delivery.attempt + 1

        if result["success"]:
            async with async_session() as session:
                await session.execute(
                    update(WebhookDelivery)
                    .where(WebhookDelivery.id == delivery.id)
                    .values(
                        status="delivered",
                        status_code=result["status_code"],
                        response_body=result.get("response_body"),
                        attempt=new_attempt,
                        delivered_at=now,
                        next_retry_at=None,
                    )
                )
                await session.commit()
            logger.info(f"Retry succeeded for delivery {delivery.id} (attempt {new_attempt})")
        else:
            # Schedule next retry or mark as failed
            if new_attempt >= delivery.max_attempts:
                new_status = "failed"
                next_retry = None
            else:
                new_status = "pending"
                delay_idx = min(new_attempt - 1, len(RETRY_DELAYS) - 1)
                next_retry = now + timedelta(seconds=RETRY_DELAYS[delay_idx])

            async with async_session() as session:
                await session.execute(
                    update(WebhookDelivery)
                    .where(WebhookDelivery.id == delivery.id)
                    .values(
                        status=new_status,
                        status_code=result["status_code"],
                        error_message=result.get("error"),
                        attempt=new_attempt,
                        next_retry_at=next_retry,
                    )
                )
                await session.commit()
            logger.info(f"Retry {new_attempt} failed for delivery {delivery.id}, status={new_status}")
