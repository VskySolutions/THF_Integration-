from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.features.caseware_cloud_intergration.models.integration_log import (
        CasewareCloudIntegrationLog,
    )


class CasewareCloudEntityEngagementMapping(Base):
    __tablename__ = "caseware_cloud_entity_engagement_mapping"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    caseware_cloud_entity_cwid: Mapped[str] = mapped_column(Text, nullable=False)
    mapitonomy_job_number: Mapped[str] = mapped_column(Text, nullable=False)
    # cw_addresses: Mapped[list[int] | None] = mapped_column(
    #     ARRAY(Integer), nullable=True
    # )
    cw_addresses: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    integration_logs: Mapped[list[CasewareCloudIntegrationLog]] = relationship(
        back_populates="entity_engagement_mapping"
    )
