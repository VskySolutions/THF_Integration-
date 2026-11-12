from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_engagements_and_tasks_integration.models.engagement_task_mapping import (
        SAPConcurEngagementTaskMapping,
    )


class EngagementTaskIntegrationStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class EngagementTaskIntegrationAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    RETRY_CREATE = "RETRY_CREATE"


class SAPConcurEngagementTaskIntegrationLog(Base):
    """Integration run log for the SAP Concur engagements & tasks sync.

    Analog of ``sap_concur_invoice_integration_log`` (invoice feature).
    ``sap_concur_engagement_task_mapping_id`` is nullable so run-level
    entries (no single mapping row) are representable; Maconomy ids carry
    the ``"N/A"`` sentinel for those entries.
    """

    __tablename__ = "sap_concur_engagement_task_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: set for per-engagement/task logs; NULL for run-level
    # entries (fetch/summary) — mirrors the invoice log's mapping FK.
    sap_concur_engagement_task_mapping_id: Mapped[uuid.UUID | None] = (
        mapped_column(
            ForeignKey("sap_concur_engagement_task_mapping.id"), nullable=True
        )
    )
    # Maconomy-side ids ("N/A" for run-level entries without a mapping).
    maconomy_jobnumber: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_tasknumber: Mapped[str] = mapped_column(Text, nullable=False)
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EngagementTaskIntegrationStatus] = mapped_column(
        Enum(
            EngagementTaskIntegrationStatus,
            name="sap_concur_engagement_task_integration_status",
        ),
        nullable=False,
    )
    action: Mapped[EngagementTaskIntegrationAction] = mapped_column(
        Enum(
            EngagementTaskIntegrationAction,
            name="sap_concur_engagement_task_integration_action",
        ),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    engagement_task_mapping: Mapped[SAPConcurEngagementTaskMapping | None] = (
        relationship(back_populates="integration_logs")
    )
