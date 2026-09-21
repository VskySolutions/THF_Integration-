import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_integration.models.expensesheet_expensereport_mapping import (
    SAPConcurExpensesheetExpenseReportMapping,
)


async def create_mapping(
    session: AsyncSession,
    maconomy_expensesheet_no: str,
    sap_concur_expensereport_id: str,
) -> SAPConcurExpensesheetExpenseReportMapping:
    mapping = SAPConcurExpensesheetExpenseReportMapping(
        maconomy_expensesheet_no=maconomy_expensesheet_no,
        sap_concur_expensereport_id=sap_concur_expensereport_id,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def list_mappings(
    session: AsyncSession, *, offset: int, limit: int
) -> list[SAPConcurExpensesheetExpenseReportMapping]:
    statement = (
        select(SAPConcurExpensesheetExpenseReportMapping)
        .order_by(SAPConcurExpensesheetExpenseReportMapping.created_on_utc.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.scalars(statement)
    return list(result)


async def get_mapping(
    session: AsyncSession, mapping_id: uuid.UUID
) -> SAPConcurExpensesheetExpenseReportMapping | None:
    return await session.get(SAPConcurExpensesheetExpenseReportMapping, mapping_id)


async def get_mapping_by_report_id(
    session: AsyncSession, report_id: str
) -> SAPConcurExpensesheetExpenseReportMapping | None:
    statement = select(SAPConcurExpensesheetExpenseReportMapping).where(
        SAPConcurExpensesheetExpenseReportMapping.sap_concur_expensereport_id == report_id
    )
    return await session.scalar(statement)
