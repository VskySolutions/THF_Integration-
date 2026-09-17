from collections.abc import Iterable
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.maconomy_caseware_cloud_intergration.models import (
    MaconomyCasewareRequestLog,
)


async def record_sync_logs(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    maconomy_instance: str,
    candidates: Iterable[dict[str, Any]],
) -> bool:
    records = list(candidates)
    failed = [candidate for candidate in records if candidate.get("syncAction") == "FAILED"]
    job_logs = [
        MaconomyCasewareRequestLog(
            request_id=request_id,
            maconomy_instance=maconomy_instance,
            job_number=_job_number(candidate),
            action=str(candidate.get("syncAction", "UNKNOWN")),
            status=(
                "FAILED"
                if candidate.get("syncAction") == "FAILED"
                else "SUCCESS"
            ),
            message=str(candidate.get("syncError", "Job completed successfully")),
            details={
                "syncAction": candidate.get("syncAction"),
                "versionnumber": candidate.get("versionnumber"),
                "text19": candidate.get("text19"),
            },
        )
        for candidate in records
    ]
    job_logs.append(
        MaconomyCasewareRequestLog(
            request_id=request_id,
            maconomy_instance=maconomy_instance,
            job_number=None,
            action="SYNC",
            status="FAILED" if failed else "SUCCESS",
            message=(
                f"Processed {len(records)} jobs; {len(failed)} failed"
            ),
            details={
                "processed": len(records),
                "failed": len(failed),
                "succeeded": len(records) - len(failed),
            },
        )
    )
    try:
        session.add_all(job_logs)
        await session.commit()
    except Exception:
        await session.rollback()
        return False
    return True


def _job_number(candidate: dict[str, Any]) -> str | None:
    value = candidate.get("jobnumber")
    return str(value) if value is not None else None
