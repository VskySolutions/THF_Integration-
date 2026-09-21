import uuid
from typing import Any, Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.maconomy_caseware_cloud_intergration.schemas import SyncJobRequest
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
)
from app.features.maconomy_caseware_cloud_intergration.routers.sync_router import (
    _checkpoint_for_existing_entity,
    _create_caseware_job,
    _mark_failed,
    _update_caseware_job,
    _candidate_batch_lock,
)
from app.features.maconomy_caseware_cloud_intergration.services.caseware_service import (
    CasewareService,
    CasewareServiceError,
)
from app.features.maconomy_caseware_cloud_intergration.services.maconomy_service import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.maconomy_caseware_cloud_intergration.services.request_log_service import (
    record_sync_logs,
)


router = APIRouter(
    prefix="/maconomy-caseware-cloud",
    tags=["maconomy-caseware-cloud-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/sync-job",
    response_model=dict[str, Any],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC
            )
        )
    ],
)
async def sync_job_by_number(
    payload: SyncJobRequest,
    request: Request,
    session: DatabaseSession,
) -> dict[str, Any]:
    job_number = payload.jobnumber
    if _candidate_batch_lock.locked():
        raise HTTPException(status_code=409, detail="A sync batch is already running")

    settings = get_settings()
    candidate: dict[str, Any] | None = None
    async with _candidate_batch_lock:
        async with (
            httpx.AsyncClient(timeout=60.0) as maconomy_client,
            httpx.AsyncClient(timeout=60.0) as caseware_client,
        ):
            try:
                maconomy = MaconomyService(maconomy_client, settings)
                candidate = await maconomy.get_job_by_number(job_number.strip())
                if candidate is None:
                    await _write_logs(
                        request,
                        session,
                        settings,
                        [{
                            "jobnumber": job_number,
                            "syncAction": "FAILED",
                            "syncError": "Maconomy job was not found",
                        }],
                    )
                    raise HTTPException(
                        status_code=404,
                        detail=f"Maconomy job {job_number} was not found",
                    )
                caseware = CasewareService(caseware_client, settings)
                await _sync_candidate(candidate, maconomy, caseware)
                await _write_logs(request, session, settings, [candidate])
                return candidate
            except (MaconomyServiceError, CasewareServiceError) as exc:
                if candidate is None:
                    await _write_logs(
                        request,
                        session,
                        settings,
                        [{"jobnumber": job_number, "syncAction": "FAILED", "syncError": str(exc)}],
                    )
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                _mark_failed(candidate, str(exc))
                await _write_logs(request, session, settings, [candidate])
                return candidate


async def _sync_candidate(
    candidate: dict[str, Any],
    maconomy: MaconomyService,
    caseware: CasewareService,
) -> None:
    job_number = candidate["jobnumber"]
    if candidate["syncAction"] == "ALREADY_SYNCED":
        return
    if candidate["syncAction"] == "TOUPDATE":
        checkpoint = await _update_caseware_job(candidate, caseware)
        saved_version = await maconomy.update_job_text19(
            job_number=job_number,
            source_version=candidate["versionnumber"],
            checkpoint=checkpoint,
            expected_text19=candidate["text19"],
        )
        candidate["text19"] = checkpoint
        candidate["versionnumber"] = saved_version
        return

    existing_entity = (
        await caseware.find_entities_by_job_numbers([job_number])
    )[job_number]
    candidate["existingCasewareEntity"] = existing_entity
    if existing_entity is None:
        created_entity, checkpoint = await _create_caseware_job(candidate, caseware)
        saved_version = await maconomy.update_job_text19(
            job_number=job_number,
            source_version=candidate["versionnumber"],
            checkpoint=checkpoint,
        )
        candidate["existingCasewareEntity"] = created_entity
        candidate["text19"] = checkpoint
        candidate["versionnumber"] = saved_version
        candidate["syncAction"] = "CREATED"
        return

    mapped_checkpoint = _checkpoint_for_existing_entity(candidate, existing_entity)
    mapped_candidate = dict(candidate)
    mapped_candidate["text19"] = mapped_checkpoint
    checkpoint = await _update_caseware_job(mapped_candidate, caseware)
    saved_version = await maconomy.update_job_text19(
        job_number=job_number,
        source_version=candidate["versionnumber"],
        checkpoint=checkpoint,
    )
    candidate["text19"] = checkpoint
    candidate["versionnumber"] = saved_version
    candidate["syncAction"] = "TOUPDATE"


async def _write_logs(
    request: Request,
    session: AsyncSession,
    settings: Any,
    candidates: list[dict[str, Any]],
) -> None:
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.UUID(str(request_id))
    await record_sync_logs(
        session,
        request_id=request_id,
        maconomy_instance=settings.maconomy_shortname,
        candidates=candidates,
    )
