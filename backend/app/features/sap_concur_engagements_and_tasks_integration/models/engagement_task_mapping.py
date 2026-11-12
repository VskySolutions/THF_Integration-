from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.sap_concur_engagements_and_tasks_integration.models.integration_log import (
        SAPConcurEngagementTaskIntegrationLog,
    )


class SAPConcurEngagementTaskMapping(Base):
    """Maconomy engagement (job) + task -> SAP Concur engagement/task linkage.

    Analog of ``sap_concur_invoice_mapping`` (invoice feature). The
    Maconomy-side identifiers are mandatory; the SAP Concur-side ids are
    nullable (resolved when the Concur-side record is known).
    """

    __tablename__ = "sap_concur_engagement_task_mapping"
    __table_args__ = (
        UniqueConstraint(
            "maconomy_jobnumber",
            "maconomy_tasknumber",
            name="uq_sap_concur_engagement_task_mapping_maconomy_jobnumber",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Maconomy-side ids: the engagement (job) number + the task number
    # within it.
    maconomy_jobnumber: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_tasknumber: Mapped[str] = mapped_column(Text, nullable=False)
    # SAP Concur-side ids (nullable until known).
    sap_concur_engagement_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    sap_concur_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[SAPConcurEngagementTaskIntegrationLog]] = (
        relationship(back_populates="engagement_task_mapping")
    )
