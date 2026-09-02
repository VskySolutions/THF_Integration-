from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.cch_axcess_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.cch_axcess_integration.models.entity_engagement_mapping import (
        CCHAxcessEntityEngagementMapping,
    )


class CCHAxcessIntegrationLog(Base):
    __tablename__ = "cch_axcess_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cch_axcess_entity_engagement_mapping_id: Mapped[uuid.UUID | None] = (
        mapped_column(
            ForeignKey("cch_axcess_entity_engagement_mapping.id"), nullable=True
        )
    )
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(IntegrationStatus, name="cch_integration_status"), nullable=False
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[IntegrationAction] = mapped_column(
        Enum(IntegrationAction, name="cch_integration_action"), nullable=False
    )
    jobnumber: Mapped[str] = mapped_column(Text, nullable=False)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    entity_engagement_mapping: Mapped[CCHAxcessEntityEngagementMapping | None] = (
        relationship(back_populates="integration_logs")
    )
