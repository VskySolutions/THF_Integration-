from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_engagements_and_tasks_integration.models.engagement_task_mapping import (
    SAPConcurEngagementTaskMapping,
)


async def create_mapping(
    session: AsyncSession,
    *,
    maconomy_jobnumber: str,
    maconomy_tasknumber: str,
) -> SAPConcurEngagementTaskMapping:
    mapping = SAPConcurEngagementTaskMapping(
        maconomy_jobnumber=maconomy_jobnumber,
        maconomy_tasknumber=maconomy_tasknumber,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


async def get_existing_pairs(
    session: AsyncSession,
    jobnumbers: list[str],
) -> set[tuple[str, str]]:
    """Return the (jobnumber, tasknumber) pairs already in the mapping.

    Engagements are represented by the (jobnumber, "") sentinel pair.
    An empty ``jobnumbers`` list short-circuits to an empty set.
    """
    if not jobnumbers:
        return set()
    statement = select(
        SAPConcurEngagementTaskMapping.maconomy_jobnumber,
        SAPConcurEngagementTaskMapping.maconomy_tasknumber,
    ).where(
        SAPConcurEngagementTaskMapping.maconomy_jobnumber.in_(jobnumbers)
    )
    result = await session.execute(statement)
    return {
        (str(jobnumber), str(tasknumber))
        for jobnumber, tasknumber in result.all()
    }
