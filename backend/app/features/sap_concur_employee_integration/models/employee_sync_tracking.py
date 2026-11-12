from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class EmployeeSyncTracking(Base):
    __tablename__ = "employee_sync_tracking"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    maconomy_employee_number = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    sap_concur_user_id = Column(
        String(128),
        nullable=True,
        index=True,
    )
    maconomy_version = Column(
        String(64),
        nullable=True,
    )
    sync_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("now()"),
    )
    synced_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=text("now()"),
    )
    error_message = Column(
        Text,
        nullable=True,
    )

    logs = relationship(
        "EmployeeSyncLog",
        back_populates="tracking",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<EmployeeSyncTracking(maconomy_employee_number={self.maconomy_employee_number}, "
            f"sap_concur_user_id={self.sap_concur_user_id}, "
            f"version={self.maconomy_version}, status={self.sync_status})>"
        )


class EmployeeSyncLog(Base):
    """Historical audit trail and error log for Maconomy-to-SAP Concur sync attempts."""

    __tablename__ = "employee_sync_log"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tracking_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employee_sync_tracking.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    maconomy_employee_number = Column(
        String(64),
        nullable=False,
        index=True,
    )
    sap_concur_user_id = Column(
        String(128),
        nullable=True,
    )
    action = Column(
        String(32),
        nullable=False,
        index=True,
    )  # e.g., 'CREATE', 'UPDATE', 'SKIP', 'RETRY'
    status = Column(
        String(20),
        nullable=False,
        index=True,
    )  # 'SUCCESS' / 'FAILED'
    old_version = Column(
        String(64),
        nullable=True,
    )
    new_version = Column(
        String(64),
        nullable=True,
    )
    message = Column(
        Text,
        nullable=True,
    )
    details = Column(
        JSONB,
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("now()"),
        index=True,
    )

    tracking = relationship("EmployeeSyncTracking", back_populates="logs")

    def __repr__(self) -> str:
        return (
            f"<EmployeeSyncLog(emp={self.maconomy_employee_number}, "
            f"action={self.action}, status={self.status})>"
        )
