from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.cch_axcess_integration.models.integration_log import CCHAxcessIntegrationLog

if TYPE_CHECKING:
    from app.features.cch_axcess_integration.models.integration_log import (
        CCHAxcessIntegrationLog,
    )


class CCHAxcessEntityEngagementMapping(Base):
    __tablename__ = "cch_axcess_entity_engagement_mapping"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cch_axcess_entity_cchid: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_job_number: Mapped[str] = mapped_column(Text, nullable=False)
    maconomy_job_version_number: Mapped[str] = mapped_column(Text, nullable=True)
    # cch_addresses: Mapped[list[dict[str, str]] | None] = mapped_column(
    #     JSONB,
    #     nullable=True,
    # )
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[CCHAxcessIntegrationLog]] = relationship(
        back_populates="entity_engagement_mapping"
    )
