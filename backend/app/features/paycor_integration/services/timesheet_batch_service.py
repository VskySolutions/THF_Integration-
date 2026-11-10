"""Database operations for Paycor timesheet batches."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.paycor_integration.models.timesheet_batch import (
    PaycorTimesheetBatch,
)


async def get_batch(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    source_start_date: date,
    source_end_date: date,
    pay_group_id: str,
    pay_period_start: date,
    pay_period_end: date,
) -> PaycorTimesheetBatch | None:
    statement = select(
        PaycorTimesheetBatch
    ).where(
        PaycorTimesheetBatch.paycor_legal_entity_id
        == legal_entity_id,
        PaycorTimesheetBatch.source_start_date
        == source_start_date,
        PaycorTimesheetBatch.source_end_date
        == source_end_date,
        PaycorTimesheetBatch.pay_group_id
        == pay_group_id,
        PaycorTimesheetBatch.pay_period_start
        == pay_period_start,
        PaycorTimesheetBatch.pay_period_end
        == pay_period_end,
    )

    return await session.scalar(statement)


async def get_or_create_batch(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    source_start_date: date,
    source_end_date: date,
    pay_group_id: str,
    pay_period_start: date,
    pay_period_end: date,
) -> tuple[PaycorTimesheetBatch, bool]:
    existing_batch = await get_batch(
        session,
        legal_entity_id=legal_entity_id,
        source_start_date=source_start_date,
        source_end_date=source_end_date,
        pay_group_id=pay_group_id,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
    )

    if existing_batch is not None:
        return existing_batch, False

    batch = PaycorTimesheetBatch(
        paycor_legal_entity_id=legal_entity_id,
        source_start_date=source_start_date,
        source_end_date=source_end_date,
        pay_group_id=pay_group_id,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
    )
    session.add(batch)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_batch = await get_batch(
            session,
            legal_entity_id=legal_entity_id,
            source_start_date=source_start_date,
            source_end_date=source_end_date,
            pay_group_id=pay_group_id,
            pay_period_start=pay_period_start,
            pay_period_end=pay_period_end,
        )

        if existing_batch is None:
            raise

        return existing_batch, False

    await session.refresh(batch)
    return batch, True


async def list_batches_for_source_range(
    session: AsyncSession,
    *,
    legal_entity_id: int,
    source_start_date: date,
    source_end_date: date,
) -> list[PaycorTimesheetBatch]:
    statement = (
        select(PaycorTimesheetBatch)
        .where(
            PaycorTimesheetBatch.paycor_legal_entity_id
            == legal_entity_id,
            PaycorTimesheetBatch.source_start_date
            == source_start_date,
            PaycorTimesheetBatch.source_end_date
            == source_end_date,
        )
        .order_by(
            PaycorTimesheetBatch.pay_group_id,
            PaycorTimesheetBatch.pay_period_start,
        )
    )

    result = await session.scalars(statement)
    return list(result.all())


async def mark_batch_accepted(
    session: AsyncSession,
    batch: PaycorTimesheetBatch,
    *,
    process_id: uuid.UUID,
) -> PaycorTimesheetBatch:
    batch.accepted_process_id = process_id
    await session.commit()
    await session.refresh(batch)
    return batch
