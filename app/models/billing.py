"""
BillingEvent — immutable ledger written by the worker after every job.

This is the source of truth for billing disputes and usage audits.
Records are NEVER updated or deleted; they capture the state of the world
at the moment the job concluded.

One row per analysis job (completed OR failed — both consume quota).
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Index
)
from app.core.database import Base


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Job identity ─────────────────────────────────────────────
    job_id = Column(String(36), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Job inputs ───────────────────────────────────────────────
    model_tier = Column(String(20), nullable=False)          # fast / balanced / max
    file_size_bytes = Column(Integer, nullable=True)
    audio_duration_s = Column(Float, nullable=True)

    # ── Job outcome ──────────────────────────────────────────────
    status = Column(String(20), nullable=False)              # completed / failed
    processing_time_ms = Column(Float, nullable=True)

    # ── Billing ──────────────────────────────────────────────────
    compute_units = Column(Integer, nullable=False, default=0)  # CU consumed (0 for failed jobs)

    # ── Timestamps ───────────────────────────────────────────────
    occurred_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_billing_user_month", "user_id", "occurred_at"),
        Index("ix_billing_key_month", "api_key_id", "occurred_at"),
    )

    def __repr__(self):
        return (
            f"<BillingEvent job={self.job_id} user={self.user_id} "
            f"tier={self.model_tier} cu={self.compute_units} status={self.status}>"
        )
