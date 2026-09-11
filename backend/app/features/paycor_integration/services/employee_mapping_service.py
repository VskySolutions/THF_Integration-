"""Database operations for Paycor employee mappings."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)


async def get_mapping_by_paycor_employee(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    paycor_employee_id: uuid.UUID,
) -> PaycorEmployeeMappingLog | None:
    statement = select(PaycorEmployeeMappingLog).where(
        PaycorEmployeeMappingLog.paycor_legal_entity_id
        == legal_entity_id,
        PaycorEmployeeMappingLog.paycor_employee_id
        == paycor_employee_id,
    )

    return await session.scalar(statement)


async def create_pending_mapping(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    paycor_employee_id: uuid.UUID,
    paycor_employee_number: str,
) -> tuple[PaycorEmployeeMappingLog, bool]:
    mapping = PaycorEmployeeMappingLog(
        paycor_legal_entity_id=legal_entity_id,
        paycor_employee_id=paycor_employee_id,
        paycor_employee_number=paycor_employee_number,
        maconomy_employee_number=None,
    )

    session.add(mapping)

    try:
        await session.commit()

    except IntegrityError:
        await session.rollback()

        existing_mapping = await get_mapping_by_paycor_employee(
            session,
            legal_entity_id=legal_entity_id,
            paycor_employee_id=paycor_employee_id,
        )

        if existing_mapping is None:
            raise

        return existing_mapping, False

    await session.refresh(mapping)

    return mapping, True


async def update_mapping(
    session: AsyncSession,
    mapping: PaycorEmployeeMappingLog,
    *,
    paycor_employee_number: str,
    maconomy_employee_number: str | None = None,
) -> PaycorEmployeeMappingLog:
    mapping.paycor_employee_number = paycor_employee_number

    if maconomy_employee_number is not None:
        mapping.maconomy_employee_number = maconomy_employee_number

    await session.commit()
    await session.refresh(mapping)

    return mapping


async def complete_mapping(
    session: AsyncSession,
    mapping: PaycorEmployeeMappingLog,
    *,
    paycor_employee_number: str,
    maconomy_employee_number: str,
) -> PaycorEmployeeMappingLog:
    return await update_mapping(
        session,
        mapping,
        paycor_employee_number=paycor_employee_number,
        maconomy_employee_number=maconomy_employee_number,
    )