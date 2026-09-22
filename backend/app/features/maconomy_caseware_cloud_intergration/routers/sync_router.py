import asyncio
from datetime import datetime, timezone
import uuid
from typing import Annotated
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services import (
    IntegrationServiceIdentifier,
    require_active_integration_service,
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
_candidate_batch_lock = asyncio.Lock()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/sync-jobs",
    response_model=list[dict[str, Any]],
    dependencies=[
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_CASEWARE_CLOUD_SYNC
            )
        )
    ],
)
async def get_job_candidates(
    request: Request,
    session: DatabaseSession,
) -> list[dict[str, Any]]:
    """Return open Maconomy jobs created or updated in the last two days."""
    if _candidate_batch_lock.locked():
        raise HTTPException(status_code=409, detail="A candidate batch is already running")

    settings = get_settings()
    async with _candidate_batch_lock:
        async with (
            httpx.AsyncClient(timeout=60.0) as maconomy_client,
            httpx.AsyncClient(timeout=60.0) as caseware_client,
        ):
            candidates: list[dict[str, Any]] = []
            try:
                maconomy = MaconomyService(maconomy_client, settings)
                candidates = await maconomy.get_recent_jobs()
                caseware = CasewareService(caseware_client, settings)
                for candidate in candidates:
                    if candidate["syncAction"] == "TOUPDATE":
                        try:
                            checkpoint = await _update_caseware_job(
                                candidate,
                                caseware,
                            )
                            saved_version = await maconomy.update_job_text19(
                                job_number=candidate["jobnumber"],
                                source_version=candidate["versionnumber"],
                                checkpoint=checkpoint,
                                expected_text19=candidate["text19"],
                            )
                        except (MaconomyServiceError, CasewareServiceError) as exc:
                            _mark_failed(candidate, str(exc))
                            continue
                        candidate["text19"] = checkpoint
                        candidate["versionnumber"] = saved_version
                        continue

                    if candidate["syncAction"] != "TOCREATE":
                        continue
                    job_number = candidate.get("jobnumber")
                    if not isinstance(job_number, str) or not job_number.strip():
                        _mark_failed(
                            candidate,
                            "Maconomy candidate has an invalid jobnumber",
                        )
                        continue

                    try:
                        existing_entity = (
                            await caseware.find_entities_by_job_numbers([job_number])
                        )[job_number]
                    except CasewareServiceError as exc:
                        _mark_failed(candidate, str(exc))
                        continue

                    candidate["existingCasewareEntity"] = existing_entity
                    if existing_entity is None:
                        try:
                            created_entity, checkpoint = await _create_caseware_job(
                                candidate,
                                caseware,
                            )
                            saved_version = await maconomy.update_job_text19(
                                job_number=job_number,
                                source_version=candidate["versionnumber"],
                                checkpoint=checkpoint,
                            )
                        except (MaconomyServiceError, CasewareServiceError) as exc:
                            _mark_failed(candidate, str(exc))
                            continue

                        candidate["existingCasewareEntity"] = created_entity
                        candidate["text19"] = checkpoint
                        candidate["versionnumber"] = saved_version
                        candidate["syncAction"] = "CREATED"
                        continue

                    try:
                        mapped_checkpoint = _checkpoint_for_existing_entity(
                            candidate,
                            existing_entity,
                        )
                        mapped_candidate = dict(candidate)
                        mapped_candidate["text19"] = mapped_checkpoint
                        checkpoint = await _update_caseware_job(
                            mapped_candidate,
                            caseware,
                        )
                        saved_version = await maconomy.update_job_text19(
                            job_number=job_number,
                            source_version=candidate["versionnumber"],
                            checkpoint=checkpoint,
                        )
                    except (MaconomyServiceError, CasewareServiceError) as exc:
                        _mark_failed(candidate, str(exc))
                        continue

                    candidate["text19"] = checkpoint
                    candidate["versionnumber"] = saved_version
                    candidate["syncAction"] = "TOUPDATE"
                request_id = getattr(request.state, "request_id", uuid.uuid4())
                if not isinstance(request_id, uuid.UUID):
                    request_id = uuid.UUID(str(request_id))
                await record_sync_logs(
                    session,
                    request_id=request_id,
                    maconomy_instance=settings.maconomy_shortname,
                    candidates=candidates,
                )
                return candidates
            except (MaconomyServiceError, CasewareServiceError) as exc:
                request_id = getattr(request.state, "request_id", uuid.uuid4())
                if not isinstance(request_id, uuid.UUID):
                    request_id = uuid.UUID(str(request_id))
                await record_sync_logs(
                    session,
                    request_id=request_id,
                    maconomy_instance=settings.maconomy_shortname,
                    candidates=candidates
                    or [{"syncAction": "FAILED", "syncError": str(exc)}],
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc


def _checkpoint_for_existing_entity(
    candidate: dict[str, Any],
    existing_entity: dict[str, Any],
) -> dict[str, Any]:
    entity_no = existing_entity.get("EntityNo")
    if not isinstance(entity_no, str) or not entity_no.strip():
        raise CasewareServiceError("Existing CaseWare entity has an invalid EntityNo")

    entity_id = existing_entity.get("CWGuid")
    try:
        entity_id = str(UUID(entity_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise CasewareServiceError(
            f"CaseWare entity {entity_no} has an invalid CWGuid"
        ) from exc

    address_id: str | None = None
    address_no: str | int | None = None
    addresses = existing_entity.get("Addresses")
    if addresses is not None:
        if not isinstance(addresses, list):
            raise CasewareServiceError(
                f"CaseWare entity {entity_no} has invalid address data"
            )
        if addresses:
            address = addresses[0]
            if not isinstance(address, dict):
                raise CasewareServiceError(
                    f"CaseWare entity {entity_no} has invalid address data"
                )
            raw_address_id = address.get("CWGuid")
            try:
                address_id = str(UUID(raw_address_id))
            except (AttributeError, TypeError, ValueError) as exc:
                raise CasewareServiceError(
                    f"CaseWare entity {entity_no} has an invalid address CWGuid"
                ) from exc
            address_no = address.get("Id")
            if isinstance(address_no, bool) or (
                address_no is not None
                and not isinstance(address_no, (str, int))
            ):
                raise CasewareServiceError(
                    f"CaseWare entity {entity_no} has an invalid address Id"
                )

    source_version = MaconomyService._parse_version(candidate.get("versionnumber"))
    return {
        "entityId": entity_id,
        "entityNo": entity_no,
        "syncedVersion": source_version,
        "addressId": address_id,
        "addressNo": address_no,
        "lastUpdateOnUTC": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }


async def _update_caseware_job(
    candidate: dict[str, Any],
    caseware: CasewareService,
) -> dict[str, Any]:
    checkpoint = candidate["text19"]
    entity_id = checkpoint["entityId"]
    entity = await caseware.update_entity(candidate, entity_id)
    owner_id = entity.get("Id")
    if isinstance(owner_id, bool) or not isinstance(owner_id, int):
        raise CasewareServiceError("CaseWare entity has an invalid numeric Id")

    addresses = await caseware.get_entity_addresses(entity_id)
    address_id = checkpoint.get("addressId")
    address_no = checkpoint.get("addressNo")
    selected_address: dict[str, Any] | None = None
    if address_id is not None:
        selected_address = next(
            (
                address
                for address in addresses
                if isinstance(address, dict)
                and isinstance(address.get("CWGuid"), str)
                and _same_guid(address["CWGuid"], address_id)
            ),
            None,
        )
        if selected_address is None:
            raise CasewareServiceError(
                f"CaseWare address {address_id} was not found on entity {entity_id}"
            )
    elif addresses:
        selected_address = addresses[0]

    if selected_address is None:
        selected_address = await caseware.create_entity_address(
            candidate,
            entity_id,
            owner_id,
        )
    else:
        selected_address_id = selected_address.get("CWGuid")
        selected_address_no = selected_address.get("Id")
        if not isinstance(selected_address_id, str) or not selected_address_id.strip():
            raise CasewareServiceError("CaseWare address has an invalid CWGuid")
        if isinstance(selected_address_no, bool) or not isinstance(
            selected_address_no, (str, int)
        ):
            raise CasewareServiceError("CaseWare address has an invalid Id")
        await caseware.update_entity_address(candidate, selected_address_id)
        address_id = selected_address_id
        address_no = selected_address_no

    address_id = selected_address.get("CWGuid")
    address_no = selected_address.get("Id")
    if not isinstance(address_id, str) or not address_id.strip():
        raise CasewareServiceError("CaseWare address has an invalid CWGuid")
    if isinstance(address_no, bool) or not isinstance(address_no, (str, int)):
        raise CasewareServiceError("CaseWare address has an invalid Id")

    source_version = MaconomyService._parse_version(candidate["versionnumber"])
    updated_checkpoint = dict(checkpoint)
    updated_checkpoint.update(
        {
            "syncedVersion": source_version + 1,
            "addressId": str(UUID(address_id)),
            "addressNo": address_no,
            "lastUpdateOnUTC": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
        }
    )
    return updated_checkpoint


async def _create_caseware_job(
    candidate: dict[str, Any],
    caseware: CasewareService,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entity = await caseware.create_entity(candidate)
    entity_id = entity.get("CWGuid")
    owner_id = entity.get("Id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise CasewareServiceError("Created CaseWare entity has an invalid CWGuid")
    if isinstance(owner_id, bool) or not isinstance(owner_id, int):
        raise CasewareServiceError("Created CaseWare entity has an invalid Id")

    address = await caseware.create_entity_address(
        candidate,
        entity_id,
        owner_id,
    )
    address_id = address.get("CWGuid")
    address_no = address.get("Id")
    if not isinstance(address_id, str) or not address_id.strip():
        raise CasewareServiceError("Created CaseWare address has an invalid CWGuid")
    if isinstance(address_no, bool) or not isinstance(address_no, (str, int)):
        raise CasewareServiceError("Created CaseWare address has an invalid Id")

    source_version = MaconomyService._parse_version(candidate["versionnumber"])
    checkpoint = {
        "entityId": str(UUID(entity_id)),
        "entityNo": str(entity.get("EntityNo") or f"VSKY-{candidate['jobnumber']}"),
        "syncedVersion": source_version + 1,
        "addressId": str(UUID(address_id)),
        "addressNo": address_no,
        "lastUpdateOnUTC": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    entity["Addresses"] = [address]
    return entity, checkpoint


def _mark_failed(candidate: dict[str, Any], message: str) -> None:
    candidate["existingCasewareEntity"] = None
    candidate["syncAction"] = "FAILED"
    candidate["syncError"] = message


def _same_guid(first: str, second: str) -> bool:
    try:
        return UUID(first) == UUID(second)
    except (AttributeError, TypeError, ValueError):
        return False
