import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.integration_services.constants import IntegrationServiceIdentifier
from app.features.integration_services.dependencies.active_service import (
    require_active_integration_service,
)
from app.features.sap_concur_vendor_integration.models.integration_log import (
    VendorIntegrationAction,
    VendorIntegrationStatus,
)
from app.features.sap_concur_vendor_integration.schemas.sap_concur_vendors import (
    RetryVendorSyncRequest,
)
from app.features.sap_concur_vendor_integration.services import (
    integration_log_service,
    retry_vendor_sync_service,
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

router = APIRouter(
    prefix="/sap-concur-vendors",
    tags=["sap-concur-vendor-integration"],
    dependencies=[
        Depends(require_api_key),
        Depends(
            require_active_integration_service(
                IntegrationServiceIdentifier.MACONOMY_SAP_CONCUR_VENDOR_SYNC
            )
        ),
    ],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def _safe_create_log(
    session: AsyncSession,
    *,
    mapping_id: uuid.UUID | None,
    sap_concur_vendor_code: str | None,
    maconomy_vendor_code: str | None,
    status_value: VendorIntegrationStatus,
    message: str,
) -> None:
    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping_id,
            sap_concur_vendor_code=sap_concur_vendor_code,
            maconomy_vendor_code=maconomy_vendor_code,
            status=status_value,
            action=VendorIntegrationAction.CREATE,
            message=message,
        )
    except Exception as exc:
        print(f"[vendor-log] failed to persist integration log: {exc}")


async def _safe_create_mapping(
    session: AsyncSession,
    *,
    sap_concur_vendor_code: str,
    maconomy_vendor_code: str,
) -> uuid.UUID | None:
    try:
        mapping = await vendor_mapping_service.create_mapping(
            session,
            sap_concur_vendor_code=sap_concur_vendor_code,
            maconomy_vendor_code=maconomy_vendor_code,
        )
        return mapping.id
    except Exception as exc:
        print(
            f"[vendor-log] failed to persist mapping for "
            f"{sap_concur_vendor_code}: {exc}"
        )
        return None


@router.post("/sync-vendors-sap-maconomy", response_model=dict[str, Any])
async def sync_vendors_sap_maconomy(session: DatabaseSession) -> dict[str, Any]:
    try:
        sap_vendors = await SAPConcurVendorService().get_approved_vendors()
    except SAPConcurVendorServiceError as exc:
        await _safe_create_log(
            session,
            mapping_id=None,
            sap_concur_vendor_code=None,
            maconomy_vendor_code=None,
            status_value=VendorIntegrationStatus.FAILED,
            message=(
                "Failed to fetch vendors from SAP Concur: "
                f"{str(exc)[:1000]}"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve vendors from SAP Concur",
        ) from exc

    concur_vendors = [
        vendor
        for vendor in sap_vendors.get("vendors") or []
        if isinstance(vendor, dict)
    ]

    if not concur_vendors:
        await _safe_create_log(
            session,
            mapping_id=None,
            sap_concur_vendor_code=None,
            maconomy_vendor_code=None,
            status_value=VendorIntegrationStatus.SKIPPED,
            message="No vendors fetched from concur",
        )
        return {"vendors": []}

    vendor_results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        maconomy_service = MaconomyService(client)
        try:
            await maconomy_service.authenticate()
            existing_vendors = await maconomy_service.get_all_vendors()
        except MaconomyServiceError as exc:
            for vendor in concur_vendors:
                vendor_code = str(vendor.get("VendorCode") or "").strip()
                await _safe_create_log(
                    session,
                    mapping_id=None,
                    sap_concur_vendor_code=vendor_code or None,
                    maconomy_vendor_code=None,
                    status_value=VendorIntegrationStatus.FAILED,
                    message=(
                        "Failed to pre-check existing Maconomy vendors: "
                        f"{str(exc)[:1000]}"
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve vendors from Maconomy",
            ) from exc

        existing_codes = {
            vendor["vendornumber"]
            for vendor in existing_vendors
            if vendor["vendornumber"]
        }
        new_vendors = [
            vendor
            for vendor in concur_vendors
            if str(vendor.get("VendorCode") or "").strip()
            not in existing_codes
        ]
        # print("New Vendors:", new_vendors)
        # return new_vendors

        for sap_vendor in concur_vendors:
            vendor_code = str(sap_vendor.get("VendorCode") or "").strip()
            if vendor_code and vendor_code in existing_codes:
                await _safe_create_log(
                    session,
                    mapping_id=None,
                    sap_concur_vendor_code=vendor_code,
                    maconomy_vendor_code=vendor_code,
                    status_value=VendorIntegrationStatus.SKIPPED,
                    message="Vendor already exists in Maconomy - skipped",
                )
                vendor_results.append(
                    {
                        "vendor_code": vendor_code,
                        "vendor_name": str(
                            sap_vendor.get("VendorName") or ""
                        ).strip(),
                        "created": False,
                        "message": "Vendor already exists in Maconomy - skipped",
                    }
                )

        for sap_vendor in new_vendors:
            vendor_code = str(sap_vendor.get("VendorCode") or "").strip()
            vendor_name = str(sap_vendor.get("VendorName") or "").strip()
            try:
                created_vendor = await maconomy_service.create_vendor(
                    sap_vendor
                )
                created_code = str(
                    created_vendor.get("vendornumber") or ""
                ).strip()
                mapping_id = await _safe_create_mapping(
                    session,
                    sap_concur_vendor_code=vendor_code,
                    maconomy_vendor_code=created_code,
                )
                await _safe_create_log(
                    session,
                    mapping_id=mapping_id,
                    sap_concur_vendor_code=vendor_code or None,
                    maconomy_vendor_code=created_code or None,
                    status_value=VendorIntegrationStatus.SUCCESS,
                    message="Vendor created in Maconomy",
                )
                vendor_results.append(
                    {
                        "vendor_code": vendor_code,
                        "vendor_name": vendor_name,
                        "created": True,
                        "message": "Vendor created successfully",
                    }
                )
            except MaconomyServiceError as exc:
                await _safe_create_log(
                    session,
                    mapping_id=None,
                    sap_concur_vendor_code=vendor_code or None,
                    maconomy_vendor_code=None,
                    status_value=VendorIntegrationStatus.FAILED,
                    message=str(exc)[:1000],
                )
                vendor_results.append(
                    {
                        "vendor_code": vendor_code,
                        "vendor_name": vendor_name,
                        "created": False,
                        "message": str(exc),
                    }
                )

    return {"vendors": vendor_results}


@router.post("/retry-vendor-sync", response_model=dict[str, Any])
async def retry_vendor_sync(
    session: DatabaseSession,
    request: RetryVendorSyncRequest,
) -> dict[str, Any]:
    """Retry-resume a single SAP Concur vendor into Maconomy."""
    vendor_code = request.vendor_code.strip()
    if not vendor_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vendor_code is required",
        )
    return await retry_vendor_sync_service.retry_vendor_sync(
        session, vendor_code=vendor_code
    )
