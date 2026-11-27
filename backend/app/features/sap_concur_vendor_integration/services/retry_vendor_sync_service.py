"""Retry workflow for SAP Concur -> Maconomy vendor creation.

Single-vendor retry: fetches the vendor from SAP Concur by code, checks
Maconomy for an existing vendornumber with a single restricted
``vendorcard/filter`` lookup, and creates the vendor only when it is
missing. Exactly ONE consolidated ``action=RETRY_CREATE`` integration-log
row is written per attempt into ``sap_concur_vendor_integration_logs``
(same table as the batch sync). Mapping rows are upserted to respect
``uq_sap_concur_vendor_mapping_sap_concur_vendor_code``.
"""

import uuid
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sap_concur_vendor_integration.models.integration_log import (
    VendorIntegrationAction,
    VendorIntegrationStatus,
)
from app.features.sap_concur_vendor_integration.services import (
    integration_log_service,
    vendor_mapping_service,
)
from app.features.sap_concur_vendor_integration.services.maconomy_services import (
    MaconomyService,
    MaconomyServiceError,
)
from app.features.sap_concur_vendor_integration.services.sap_concur_services import (
    SAPConcurVendorService,
    SAPConcurVendorServiceError,
)

_RETRY_TIMEOUT_SECONDS = 60.0


async def _safe_retry_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    sap_concur_vendor_code: str | None,
    maconomy_vendor_code: str | None,
    status_value: VendorIntegrationStatus,
    message: str,
) -> None:
    """Non-fatal wrapper: a logging failure must never mask the outcome."""
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            sap_concur_vendor_code=sap_concur_vendor_code,
            maconomy_vendor_code=maconomy_vendor_code,
            status=status_value,
            action=VendorIntegrationAction.RETRY_CREATE,
            message=message,
        )
    except Exception:
        pass


async def _upsert_mapping(
    session: AsyncSession,
    *,
    sap_concur_vendor_code: str,
    maconomy_vendor_code: str,
) -> uuid.UUID | None:
    """Create or heal the mapping row for the retried vendor.

    The mapping table is unique on ``sap_concur_vendor_code``, so an
    existing row is updated instead of re-inserted.
    """
    try:
        mapping = await vendor_mapping_service.get_by_sap_code(
            session, sap_concur_vendor_code
        )
        if mapping is None:
            mapping = await vendor_mapping_service.create_mapping(
                session,
                sap_concur_vendor_code=sap_concur_vendor_code,
                maconomy_vendor_code=maconomy_vendor_code,
            )
        elif str(mapping.maconomy_vendor_code or "").strip() != (
            maconomy_vendor_code
        ):
            mapping.maconomy_vendor_code = maconomy_vendor_code
            await session.commit()
        return mapping.id
    except Exception:
        return None


async def retry_vendor_sync(
    session: AsyncSession,
    *,
    vendor_code: str,
) -> dict[str, Any]:
    """Retry one SAP Concur vendor into Maconomy.

    Returns a structured dict with ``vendor_code``, ``status``
    (SUCCESS/SKIPPED/FAILED), ``message`` and ``result``. Raises 400
    for a blank code, 404 when Concur has no such approved vendor, and
    502 on Concur/Maconomy connectivity failures (each already logged
    with ``action=RETRY_CREATE`` before raising).
    """
    normalized_code = vendor_code.strip()
    if not normalized_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vendor_code is required",
        )

    try:
        return await _run_retry_vendor_sync(
            session, vendor_code=normalized_code
        )
    except HTTPException:
        # Inner paths already wrote their single log row before raising.
        raise
    except Exception as exc:
        # Gap protection: unexpected error that bypassed all inner log paths.
        await _safe_retry_log(
            session,
            mapping_id=None,
            sap_concur_vendor_code=normalized_code,
            maconomy_vendor_code=None,
            status_value=VendorIntegrationStatus.FAILED,
            message=f"Retry processing failed: {str(exc)[:1000]}",
        )
        raise


async def _run_retry_vendor_sync(
    session: AsyncSession,
    *,
    vendor_code: str,
) -> dict[str, Any]:
    try:
        concur_vendor = await SAPConcurVendorService().get_vendor_by_code(
            vendor_code
        )
    except SAPConcurVendorServiceError as exc:
        await _safe_retry_log(
            session,
            mapping_id=None,
            sap_concur_vendor_code=vendor_code,
            maconomy_vendor_code=None,
            status_value=VendorIntegrationStatus.FAILED,
            message=(
                "Failed to fetch vendor from SAP Concur: "
                f"{str(exc)[:1000]}"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve vendor from SAP Concur",
        ) from exc

    if concur_vendor is None:
        await _safe_retry_log(
            session,
            mapping_id=None,
            sap_concur_vendor_code=vendor_code,
            maconomy_vendor_code=None,
            status_value=VendorIntegrationStatus.FAILED,
            message="Vendor not found in SAP Concur",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_code} not found in SAP Concur",
        )

    async with httpx.AsyncClient(
        timeout=_RETRY_TIMEOUT_SECONDS
    ) as client:
        maconomy_service = MaconomyService(client)
        try:
            await maconomy_service.authenticate()
            existing_vendor = await maconomy_service.get_vendor_by_code(
                vendor_code
            )
        except MaconomyServiceError as exc:
            await _safe_retry_log(
                session,
                mapping_id=None,
                sap_concur_vendor_code=vendor_code,
                maconomy_vendor_code=None,
                status_value=VendorIntegrationStatus.FAILED,
                message=(
                    "Failed to pre-check existing Maconomy vendor: "
                    f"{str(exc)[:1000]}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to check vendor in Maconomy",
            ) from exc

        if existing_vendor is not None:
            existing_code = str(
                existing_vendor.get("vendornumber") or ""
            ).strip()
            message = "Vendor already exists in Maconomy - skipped"
            await _safe_retry_log(
                session,
                mapping_id=None,
                sap_concur_vendor_code=vendor_code,
                maconomy_vendor_code=existing_code or None,
                status_value=VendorIntegrationStatus.SKIPPED,
                message=message,
            )
            return {
                "vendor_code": vendor_code,
                "status": "SKIPPED",
                "message": message,
                "result": {
                    "created": False,
                    "maconomy_vendor_code": existing_code,
                },
            }

        try:
            created_vendor = await maconomy_service.create_vendor(
                concur_vendor
            )
        except MaconomyServiceError as exc:
            await _safe_retry_log(
                session,
                mapping_id=None,
                sap_concur_vendor_code=vendor_code,
                maconomy_vendor_code=None,
                status_value=VendorIntegrationStatus.FAILED,
                message=str(exc)[:1000],
            )
            return {
                "vendor_code": vendor_code,
                "status": "FAILED",
                "message": str(exc),
                "result": {"created": False},
            }

        created_code = str(
            created_vendor.get("vendornumber") or ""
        ).strip()
        mapping_id = await _upsert_mapping(
            session,
            sap_concur_vendor_code=vendor_code,
            maconomy_vendor_code=created_code,
        )
        message = "Vendor created in Maconomy"
        await _safe_retry_log(
            session,
            mapping_id=mapping_id,
            sap_concur_vendor_code=vendor_code,
            maconomy_vendor_code=created_code or None,
            status_value=VendorIntegrationStatus.SUCCESS,
            message=message,
        )
        return {
            "vendor_code": vendor_code,
            "status": "SUCCESS",
            "message": message,
            "result": {
                "created": True,
                "maconomy_vendor_code": created_code,
                "mapping_id": str(mapping_id) if mapping_id else None,
            },
        }
