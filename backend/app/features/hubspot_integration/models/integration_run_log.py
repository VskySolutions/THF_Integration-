import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HubSpotIntegrationRunLog(Base):
    """Sanitized operational summary for one Maconomy-to-HubSpot run."""

    __tablename__ = "hubspot_integration_run_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(index=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    maconomy_instance: Mapped[str] = mapped_column(Text, nullable=False)
    started_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customers_discovered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    customers_succeeded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    contacts_discovered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    contacts_succeeded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    associations_succeeded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    checkpoints_succeeded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_message: Mapped[str] = mapped_column(Text, nullable=False)
    failure_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
