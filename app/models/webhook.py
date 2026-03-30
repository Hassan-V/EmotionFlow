"""
Webhook ORM models.

Users register webhook endpoints to receive push notifications
when analysis jobs complete (or fail) instead of polling.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Webhook(Base):
    """User-registered webhook endpoint."""
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    url = Column(String(2048), nullable=False)
    secret = Column(String(255), nullable=False)  # HMAC-SHA256 signing secret
    name = Column(String(100), nullable=False, default="Default Webhook")
    is_active = Column(Boolean, default=True, nullable=False)

    # Event filters — which events to deliver (comma-separated or JSON list)
    events = Column(String(500), nullable=False, default="job.completed,job.failed")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_webhooks_user_active", "user_id", "is_active"),
    )

    def __repr__(self):
        return f"<Webhook {self.id} user={self.user_id} url={self.url[:40]}>"


class WebhookDelivery(Base):
    """Delivery attempt log — tracks each webhook fire for debugging + retry."""
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), nullable=False, index=True)

    event_type = Column(String(50), nullable=False)  # job.completed, job.failed
    payload = Column(JSON, nullable=False)

    # Delivery status
    status = Column(String(20), nullable=False, default="pending")
    # pending → delivered → failed
    status_code = Column(Integer, nullable=True)  # HTTP response code from target
    response_body = Column(Text, nullable=True)  # First 1KB of response
    error_message = Column(Text, nullable=True)

    attempt = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    webhook = relationship("Webhook", back_populates="deliveries")

    __table_args__ = (
        Index("ix_webhook_deliveries_status_retry", "status", "next_retry_at"),
        Index("ix_webhook_deliveries_job", "job_id"),
    )

    def __repr__(self):
        return f"<WebhookDelivery {self.id} webhook={self.webhook_id} status={self.status}>"
