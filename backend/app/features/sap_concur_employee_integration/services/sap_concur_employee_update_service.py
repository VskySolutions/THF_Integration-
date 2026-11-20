"""SAP Concur Employee Update and Tracking Service.

Handles:
1. Proactive lookup of existing SAP Concur users via Identity SCIM search (.search).
2. Adoption of pre-existing users without duplicate 409 errors.
3. SCIM 2.0 User Creation (POST /profile/v4/Users) and Updates (PUT /profile/v4/Users/{id}).
4. Real-time state ledger tracking in `employee_sync_tracking`.
5. Audit and error logging in `employee_sync_log`.
6. Delta version comparison against Maconomy employee record version.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.features.sap_concur_employee_integration.mappers.employee_mapper import (
    ENTERPRISE_USER_SCHEMA,
    map_maconomy_employee_to_scim_patch,
    map_maconomy_employee_to_scim_user,
)
from app.features.sap_concur_employee_integration.models.employee_sync_tracking import (
    EmployeeSyncLog,
    EmployeeSyncTracking,
)
from app.features.sap_concur_employee_integration.services.sap_concur_service import (
    SCIM_CONTENT_TYPE,
    SAPConcurEmployeeService,
    SAPConcurEmployeeServiceError,
)

logger = logging.getLogger(__name__)

SCIM_SEARCH_SCHEMA = "urn:ietf:params:scim:api:messages:concur:2.0:SearchRequest"


class SAPConcurEmployeeUpdateService:
    """Service for tracking Maconomy-to-Concur sync state, executing updates, and audit logging."""

    def __init__(
        self,
        db: AsyncSession,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.settings = settings or get_settings()
        self.concur_base_service = SAPConcurEmployeeService(
            client=self.client,
            settings=self.settings,
        )
        self.timeout = 60.0

    # -------------------------------------------------------------------------
    # Database Tracking & Logging
    # -------------------------------------------------------------------------

    async def get_tracking(self, maconomy_employee_number: str) -> EmployeeSyncTracking | None:
        """Fetch tracking record by Maconomy Employee Number."""
        stmt = select(EmployeeSyncTracking).where(
            EmployeeSyncTracking.maconomy_employee_number == str(maconomy_employee_number).strip()
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def add_log(
        self,
        *,
        maconomy_employee_number: str,
        action: str,
        status: str,
        tracking_id: Any | None = None,
        sap_concur_user_id: str | None = None,
        old_version: str | None = None,
        new_version: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> EmployeeSyncLog:
        """Create an audit/error log entry in `employee_sync_log`."""
        log_entry = EmployeeSyncLog(
            tracking_id=tracking_id,
            maconomy_employee_number=str(maconomy_employee_number).strip(),
            sap_concur_user_id=sap_concur_user_id,
            action=action,
            status=status,
            old_version=str(old_version) if old_version is not None else None,
            new_version=str(new_version) if new_version is not None else None,
            message=message,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        try:
            self.db.add(log_entry)
            await self.db.commit()
            await self.db.refresh(log_entry)
            return log_entry
        except Exception:
            await self.db.rollback()
            raise

    async def record_sync_state(
        self,
        *,
        maconomy_employee_number: str,
        sap_concur_user_id: str | None,
        maconomy_version: str | int | None,
        sync_status: str,
        action: str,
        old_version: str | None = None,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> EmployeeSyncTracking:
        """Upsert tracking state and record historical log entry."""
        clean_num = str(maconomy_employee_number).strip()
        tracking = await self.get_tracking(clean_num)
        now = datetime.now(timezone.utc)
        version_str = str(maconomy_version) if maconomy_version is not None else None

        if tracking is None:
            tracking = EmployeeSyncTracking(
                maconomy_employee_number=clean_num,
                sap_concur_user_id=sap_concur_user_id,
                maconomy_version=version_str,
                sync_status=sync_status,
                created_at=now,
                synced_at=now if sync_status == "SUCCESS" else None,
                updated_at=now,
                error_message=error_message,
            )
            self.db.add(tracking)
        else:
            if sap_concur_user_id:
                tracking.sap_concur_user_id = sap_concur_user_id
            if sync_status == "SUCCESS":
                if version_str is not None:
                    tracking.maconomy_version = version_str
                tracking.synced_at = now
                tracking.error_message = None
            else:
                tracking.error_message = error_message
            tracking.sync_status = sync_status
            tracking.updated_at = now

        try:
            await self.db.commit()
            await self.db.refresh(tracking)
        except Exception:
            await self.db.rollback()
            raise

        # Write to audit log
        await self.add_log(
            tracking_id=tracking.id,
            maconomy_employee_number=clean_num,
            sap_concur_user_id=tracking.sap_concur_user_id or sap_concur_user_id,
            action=action,
            status=sync_status,
            old_version=old_version,
            new_version=version_str,
            message=error_message if sync_status == "FAILED" else f"Successfully performed {action}",
            details=details,
        )

        return tracking

    # -------------------------------------------------------------------------
    # SAP Concur SCIM API Client Methods
    # -------------------------------------------------------------------------

    async def find_concur_user(
        self,
        email: str | None = None,
        employee_number: str | None = None,
    ) -> dict[str, Any] | None:
        """Search SAP Concur for existing user using verified Identity SCIM Search endpoint."""
        base_url = str(self.settings.sap_concur_api_base_url).rstrip("/")
        search_url = f"{base_url}/profile/identity/v4.1/Users/.search"

        queries = []
        if employee_number:
            clean_num = str(employee_number).strip()
            queries.append(f'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:employeeNumber eq "{clean_num}"')
        if email:
            clean_email = email.strip()
            queries.append(f'emails.value eq "{clean_email}"')
            queries.append(f'userName eq "{clean_email}"')
            queries.append(f'userName eq "{clean_email}.uat"')

        scim_headers = self.concur_base_service._scim_headers()
        for filter_expr in queries:
            body = {
                "schemas": [SCIM_SEARCH_SCHEMA],
                "filter": filter_expr,
            }
            try:
                if self.client is not None:
                    resp = await self.concur_base_service._request_with_auth(
                        self.client, "POST", search_url, headers=scim_headers, json=body
                    )
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await self.concur_base_service._request_with_auth(
                            client, "POST", search_url, headers=scim_headers, json=body
                        )

                if resp.status_code == 200:
                    data = resp.json()
                    resources = data.get("Resources", [])
                    if resources:
                        logger.info("Found existing SAP Concur user by filter '%s': ID=%s", filter_expr, resources[0].get("id"))
                        return resources[0]
            except Exception as exc:
                logger.warning("Error searching Concur user with filter '%s': %s", filter_expr, exc)

        return None

    def _prepare_scim_payload(self, maconomy_employee: dict[str, Any]) -> dict[str, Any]:
        """Map Maconomy employee to SCIM user and inject required Concur schema parameters."""
        payload = map_maconomy_employee_to_scim_user(maconomy_employee)

        # Concur enterprise extension requires companyId and ISO-8601 UTC Z format for startDate
        enterprise = payload.get(ENTERPRISE_USER_SCHEMA, {})
        if enterprise:
            # Use configured companyId with fallback to sandbox default
            company_id = getattr(self.settings, "sap_concur_company_id", "f7255b65-38e0-458f-ab3d-40856e011c0b")
            enterprise["companyId"] = company_id
            # Location is rejected by single user endpoint, pop it safely
            enterprise.pop("location", None)
            start_date = enterprise.get("startDate")
            if start_date and not str(start_date).endswith("Z"):
                # Normalize format: YYYY-MM-DD'T'hh:mm:ss'Z'
                date_part = str(start_date).split("T")[0]
                enterprise["startDate"] = f"{date_part}T00:00:00Z"

        return payload

    async def create_concur_user(self, maconomy_employee: dict[str, Any]) -> dict[str, Any]:
        """Create new user in SAP Concur via SCIM 2.0 POST /profile/v4/Users."""
        base_url = str(self.settings.sap_concur_api_base_url).rstrip("/")
        create_url = f"{base_url}/profile/v4/Users"
        payload = self._prepare_scim_payload(maconomy_employee)
        scim_headers = self.concur_base_service._scim_headers()

        if self.client is not None:
            resp = await self.concur_base_service._request_with_auth(
                self.client, "POST", create_url, headers=scim_headers, json=payload
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await self.concur_base_service._request_with_auth(
                    client, "POST", create_url, headers=scim_headers, json=payload
                )

        if resp.status_code in (200, 201, 202):
            return resp.json()

        error_text = resp.text
        raise SAPConcurEmployeeServiceError(f"Concur user creation returned HTTP {resp.status_code}: {error_text}")

    async def update_concur_user(
        self,
        sap_concur_user_id: str,
        maconomy_employee: dict[str, Any],
    ) -> dict[str, Any]:
        """Update existing user in SAP Concur via SCIM 2.0 PATCH /profile/v4/Users/{userId}."""
        base_url = str(self.settings.sap_concur_api_base_url).rstrip("/")
        update_url = f"{base_url}/profile/v4/Users/{sap_concur_user_id.strip()}"
        payload = map_maconomy_employee_to_scim_patch(maconomy_employee)
        scim_headers = self.concur_base_service._scim_headers()

        if self.client is not None:
            resp = await self.concur_base_service._request_with_auth(
                self.client, "PATCH", update_url, headers=scim_headers, json=payload
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await self.concur_base_service._request_with_auth(
                    client, "PATCH", update_url, headers=scim_headers, json=payload
                )

        if resp.status_code in (200, 202, 204):
            try:
                return resp.json()
            except Exception:
                return {"status": resp.status_code, "detail": "Updated successfully"}

        error_text = resp.text
        raise SAPConcurEmployeeServiceError(f"Concur user update returned HTTP {resp.status_code}: {error_text}")

    # -------------------------------------------------------------------------
    # Comprehensive Sync Decision Engine
    # -------------------------------------------------------------------------

    async def sync_or_update_employee(
        self,
        maconomy_employee: dict[str, Any],
    ) -> dict[str, Any]:
        """Executes the full 3-way synchronization algorithm:
        1. If in DB and version unchanged -> SKIP
        2. If in DB and version changed -> UPDATE Concur
        3. If NOT in DB -> Search Concur:
           - Found in Concur -> Adopt Concur UUID, UPDATE Concur, Save to DB
           - Not in Concur -> CREATE in Concur, Save to DB
        """
        emp_number = (
            maconomy_employee.get("employeenumber")
            or maconomy_employee.get("employee_number")
            or maconomy_employee.get("EmployeeNumber")
        )
        email = (
            maconomy_employee.get("electronicmailaddress")
            or maconomy_employee.get("email")
            or maconomy_employee.get("ElectronicMailAddress")
        )

        if not emp_number:
            return {"action": "SKIPPED", "reason": "Missing employeenumber"}

        if email == (""):
            return {"action": "SKIPPED", "reason": "Missing email"}


        emp_number = str(emp_number).strip()
        # Priority: versionnumber is canonical. Check is not None to avoid 0 evaluating to False (falsy bug).
        live_version = None
        for key in ("versionnumber", "versionNumber", "rowVersion", "version_number"):
            if key in maconomy_employee and maconomy_employee[key] is not None:
                live_version = maconomy_employee[key]
                break

        tracking = await self.get_tracking(emp_number)

        # ---------------------------------------------------------------------
        # SCENARIO 1: EMPLOYEE FOUND IN OUR DB
        # ---------------------------------------------------------------------
        if tracking is not None:
            stored_version = tracking.maconomy_version

            # Integer version comparison — prevents wrong skips like "9" > "10" in string
            if live_version is not None and stored_version is not None and tracking.sync_status == "SUCCESS":
                try:
                    live_v = int(str(live_version).strip())
                    stored_v = int(str(stored_version).strip())
                except (ValueError, TypeError):
                    live_v = str(live_version).strip()
                    stored_v = str(stored_version).strip()
                if live_v <= stored_v:
                    return {
                        "action": "SKIPPED",
                        "employee_number": emp_number,
                        "reason": f"Version not newer (Maconomy: {live_v}, DB: {stored_v})",
                    }

            # Version changed or previous failure -> Trigger Concur Update
            concur_id = tracking.sap_concur_user_id
            if not concur_id:
                # Missing Concur ID -> find or create
                existing_user = await self.find_concur_user(email, emp_number)
                concur_id = existing_user.get("id") if existing_user else None

            if concur_id:
                try:
                    update_res = await self.update_concur_user(concur_id, maconomy_employee)
                    await self.record_sync_state(
                        maconomy_employee_number=emp_number,
                        sap_concur_user_id=concur_id,
                        maconomy_version=live_version,
                        sync_status="SUCCESS",
                        action="UPDATE",
                        old_version=stored_version,
                        details=update_res,
                    )
                    return {
                        "action": "UPDATED",
                        "employee_number": emp_number,
                        "status": "SUCCESS",
                        "concur_user_id": concur_id,
                    }
                except Exception as exc:
                    await self.record_sync_state(
                        maconomy_employee_number=emp_number,
                        sap_concur_user_id=concur_id,
                        maconomy_version=stored_version,  # preserve previous version on failure
                        sync_status="FAILED",
                        action="UPDATE",
                        old_version=stored_version,
                        error_message=str(exc),
                        details={"error": str(exc)},
                    )
                    return {
                        "action": "FAILED_UPDATE",
                        "employee_number": emp_number,
                        "error": str(exc),
                    }
            else:
                # Concur ID not found in DB or Concur search -> SKIP (creation handled via trigger)
                logger.info("Employee %s has tracking record but no SAP Concur user found. Skipping creation.", emp_number)
                return {
                    "action": "SKIPPED",
                    "employee_number": emp_number,
                    "reason": "Employee not found in SAP Concur (creation handled via trigger)",
                }

        # ---------------------------------------------------------------------
        # SCENARIO 2: EMPLOYEE NOT FOUND IN OUR DB
        # ---------------------------------------------------------------------
        logger.info("Employee %s not in local DB. Checking SAP Concur for existing account...", emp_number)
        existing_concur_user = await self.find_concur_user(email, emp_number)

        # User found in SAP Concur -> Record tracking and execute UPDATE
        if existing_concur_user is not None:
            concur_id = existing_concur_user.get("id")
            logger.info("Found existing Concur User %s for employee %s. Updating...", concur_id, emp_number)
            try:
                update_res = await self.update_concur_user(concur_id, maconomy_employee)
                await self.record_sync_state(
                    maconomy_employee_number=emp_number,
                    sap_concur_user_id=concur_id,
                    maconomy_version=live_version,
                    sync_status="SUCCESS",
                    action="UPDATE",
                    old_version=None,
                    details=update_res,
                )
                return {
                    "action": "UPDATED",
                    "employee_number": emp_number,
                    "status": "SUCCESS",
                    "concur_user_id": concur_id,
                }
            except Exception as exc:
                await self.record_sync_state(
                    maconomy_employee_number=emp_number,
                    sap_concur_user_id=concur_id,
                    maconomy_version=None,
                    sync_status="FAILED",
                    action="UPDATE",
                    old_version=None,
                    error_message=str(exc),
                    details={"error": str(exc)},
                )
                return {
                    "action": "FAILED_UPDATE",
                    "employee_number": emp_number,
                    "error": str(exc),
                }

        # Employee not found in SAP Concur -> Direct SKIP (creation is trigger-only)
        logger.info("Employee %s not in SAP Concur. Skipping (creation handled via trigger)...", emp_number)
        return {
            "action": "SKIPPED",
            "employee_number": emp_number,
            "reason": "Employee not found in SAP Concur (creation handled via trigger)",
        }
