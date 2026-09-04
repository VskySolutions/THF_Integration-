from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base
from app.features.paycor_integration.constants import (
    EmployeeStatus,
)

if TYPE_CHECKING:
    from app.features.paycor_integration.models.integration_log import (
        PaycorIntegrationLog,
    )


class PaycorEmployeeMappingLog(Base):
    __tablename__ = "paycor_employee_mapping_log"

    __table_args__ = (
        UniqueConstraint(
            "paycor_legal_entity_id",
            "paycor_onboarding_employee_id",
            name=(
                "uq_paycor_mapping_legal_entity_"
                "onboarding_employee"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    paycor_onboarding_employee_id: Mapped[uuid.UUID] = (
        mapped_column(nullable=False)
    )

    paycor_legal_entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    paycor_employee_number: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    maconomy_employee_number: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    employee_status: Mapped[EmployeeStatus] = mapped_column(
        Enum(
            EmployeeStatus,
            name="paycor_employee_status",
        ),
        nullable=False,
    )

    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    integration_logs: Mapped[list[PaycorIntegrationLog]] = (
        relationship(
            back_populates="employee_mapping_log",
        )
    )