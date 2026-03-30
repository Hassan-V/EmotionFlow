from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Text, JSON, ForeignKey, Enum, Index
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True)  # null = JWT auth

    # Input
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    audio_format = Column(String(10), nullable=False)
    model_tier = Column(String(20), nullable=False, default="balanced")  # fast, balanced, max

    # Status
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending -> processing -> completed -> failed
    error_message = Column(Text, nullable=True)

    # Results (stored as JSON)
    result = Column(JSON, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    overall_sentiment = Column(String(50), nullable=True)

    # Timing
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_time_ms = Column(Float, nullable=True)

    user = relationship("User", back_populates="analysis_jobs")

    __table_args__ = (
        Index("ix_analysis_jobs_user_status", "user_id", "status"),
        Index("ix_analysis_jobs_created", "created_at"),
    )

    def __repr__(self):
        return f"<AnalysisJob {self.job_id} [{self.status}]>"
