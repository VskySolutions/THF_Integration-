from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base
from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)

if TYPE_CHECKING:
    from app.features.paycor_integration.models.employee_mapping_log import (
        PaycorEmployeeMappingLog,
    )


class PaycorIntegrationLog(Base):
    __tablename__ = "paycor_integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    paycor_employee_mapping_log_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        ForeignKey("paycor_employee_mapping_log.id"),
        nullable=True,
    )

    paycor_onboarding_employee_id: Mapped[uuid.UUID] = (
        mapped_column(nullable=False)
    )

    instance: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    base_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(
            IntegrationStatus,
            name="paycor_integration_status",
        ),
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    action: Mapped[IntegrationAction] = mapped_column(
        Enum(
            IntegrationAction,
            name="paycor_integration_action",
        ),
        nullable=False,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    employee_mapping_log: Mapped[
        PaycorEmployeeMappingLog | None
    ] = relationship(
        back_populates="integration_logs",
    )