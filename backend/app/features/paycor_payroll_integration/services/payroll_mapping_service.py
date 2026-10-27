"""Database operations for Paycor Payroll journal mappings."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_payroll_integration.models.payroll_journal_mapping_log import (
    PaycorPayrollJournalMappingLog,
)


async def get_mapping_by_planner(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    planner_id: str,
) -> PaycorPayrollJournalMappingLog | None:
    statement = select(PaycorPayrollJournalMappingLog).where(
        PaycorPayrollJournalMappingLog.paycor_legal_entity_id
        == legal_entity_id,
        PaycorPayrollJournalMappingLog.paycor_planner_id
        == planner_id,
    )

    return await session.scalar(statement)


async def create_pending_mapping(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    planner_id: str,
    run_type: str | None = None,
) -> tuple[PaycorPayrollJournalMappingLog, bool]:
    mapping = PaycorPayrollJournalMappingLog(
        paycor_legal_entity_id=legal_entity_id,
        paycor_planner_id=planner_id,
        paycor_run_type=run_type,
        maconomy_journal_number=None,
        maconomy_instance_id=None,
    )

    session.add(mapping)

    try:
        await session.commit()

    except IntegrityError:
        await session.rollback()

        existing_mapping = await get_mapping_by_planner(
            session,
            legal_entity_id=legal_entity_id,
            planner_id=planner_id,
        )

        if existing_mapping is None:
            raise

        return existing_mapping, False

    await session.refresh(mapping)

    return mapping, True


async def update_mapping(
    session: AsyncSession,
    mapping: PaycorPayrollJournalMappingLog,
    *,
    run_type: str | None = None,
    maconomy_journal_number: str | None = None,
    maconomy_instance_id: str | None = None,
) -> PaycorPayrollJournalMappingLog:
    if run_type is not None:
        mapping.paycor_run_type = run_type

    if maconomy_journal_number is not None:
        mapping.maconomy_journal_number = maconomy_journal_number

    if maconomy_instance_id is not None:
        mapping.maconomy_instance_id = maconomy_instance_id

    await session.commit()
    await session.refresh(mapping)

    return mapping


async def complete_mapping(
    session: AsyncSession,
    mapping: PaycorPayrollJournalMappingLog,
    *,
    maconomy_journal_number: str,
    maconomy_instance_id: str | None = None,
) -> PaycorPayrollJournalMappingLog:
    return await update_mapping(
        session,
        mapping,
        maconomy_journal_number=maconomy_journal_number,
        maconomy_instance_id=maconomy_instance_id,
    )


async def list_completed_mappings(
    session: AsyncSession,
) -> list[PaycorPayrollJournalMappingLog]:
    statement = select(
        PaycorPayrollJournalMappingLog
    ).where(
        PaycorPayrollJournalMappingLog
        .maconomy_journal_number
        .is_not(None),
    )

    result = await session.scalars(statement)

    return list(result)
