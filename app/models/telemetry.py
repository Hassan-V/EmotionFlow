from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Text, Index
)
from app.core.database import Base


class APILog(Base):
    __tablename__ = "api_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    path = Column(String(500), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    process_time_ms = Column(Float, nullable=False)
    client_ip = Column(String(45), nullable=True)  # supports IPv6
    user_agent = Column(String(500), nullable=True)
    request_size_bytes = Column(Integer, nullable=True)
    response_size_bytes = Column(Integer, nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_api_logs_created", "created_at"),
        Index("ix_api_logs_path_method", "path", "method"),
        Index("ix_api_logs_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<APILog {self.method} {self.path} [{self.status_code}] {self.process_time_ms:.0f}ms>"
