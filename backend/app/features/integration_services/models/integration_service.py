import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntegrationService(Base):
    __tablename__ = "integration_service"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    identifier_unique_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    source_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_on_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
