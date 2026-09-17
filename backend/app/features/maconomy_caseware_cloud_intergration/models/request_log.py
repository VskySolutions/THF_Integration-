import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MaconomyCasewareRequestLog(Base):
    """Append-only request/job outcomes; never used to decide synchronization."""

    __tablename__ = "maconomy_caseware_cloud_request_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(index=True)
    maconomy_instance: Mapped[str] = mapped_column(Text)
    job_number: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
