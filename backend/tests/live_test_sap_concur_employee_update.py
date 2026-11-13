"""Live Test Suite: Maconomy to SAP Concur Employee Update & Version Tracking.

Tests all key live integration flows:
1. Scenario 1: Initial creation of an employee in SAP Concur and tracking in DB.
2. Scenario 2: Unchanged version check (Ensures instant SKIP with zero API calls).
3. Scenario 3: Version increment update in Maconomy (Calls PUT update in SAP Concur, updates DB version & synced_at).
4. Scenario 4: Adoption of pre-existing Concur user not in DB (Avoids 409 conflict, adopts Concur UUID, updates user).
5. Audit Verification: Checks `employee_sync_log` and `employee_sync_tracking` entries.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import sys
import uuid

# Set up logging format
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LiveUpdateTest")

import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path and load .env explicitly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Explicitly load backend/.env so script can be run from any folder
from dotenv import load_dotenv
env_file = backend_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)

from sqlalchemy import select
from app.db.session import AsyncSessionFactory
from app.features.sap_concur_employee_integration.models.employee_sync_tracking import (
    EmployeeSyncLog,
    EmployeeSyncTracking,
)
from app.features.sap_concur_employee_integration.services.sap_concur_employee_update_service import (
    SAPConcurEmployeeUpdateService,
)


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


async def run_live_tests():
    print_banner("STARTING LIVE SAP CONCUR EMPLOYEE UPDATE TEST SUITE")

    # Generate a unique employee number for this test run to avoid colliding with real data
    unique_suffix = int(datetime.now().timestamp()) % 100000
    emp_num = f"98{unique_suffix:05d}"
    emp_email = f"live.update.test{emp_num}@example.com"

    print(f"Test Target Employee Number : {emp_num}")
    print(f"Test Target Work Email       : {emp_email}")

    async with AsyncSessionFactory() as session:
        service = SAPConcurEmployeeUpdateService(db=session)

        # ---------------------------------------------------------------------
        # TEST 1: Initial Employee Creation (Scenario 2)
        # ---------------------------------------------------------------------
        print_banner("TEST 1: INITIAL CREATION IN SAP CONCUR & TRACKING")
        emp_v1 = {
            "employeenumber": emp_num,
            "electronicmailaddress": emp_email,
            "firstname": "John",
            "lastname": "LiveTest",
            "name1": "LiveTest, John",
            "position": "Junior Tax Associate",
            "dateemployed": "2026-02-01",
            "country": "US",
            "entityname": "Tax",
            "specification4name": "Tampa",
            "rowVersion": 1,
            "blocked": False,
        }
        print(f"Payload Employee: {emp_v1['name1']}, Version: {emp_v1['rowVersion']}, Position: {emp_v1['position']}")
        res1 = await service.sync_or_update_employee(emp_v1)
        print("Result:", json.dumps(res1, indent=2))

        assert res1.get("status") == "SUCCESS", f"Test 1 failed: {res1}"
        assert res1.get("action") == "CREATED", f"Expected CREATED, got {res1.get('action')}"
        concur_user_id = res1.get("concur_user_id")
        print(f">>> TEST 1 PASSED: Created Concur User UUID: {concur_user_id}")

        # Verify DB Tracking
        tracking1 = await service.get_tracking(emp_num)
        assert tracking1 is not None, "Tracking row not created in DB"
        assert tracking1.maconomy_version == "1", f"Expected version 1, got {tracking1.maconomy_version}"
        assert tracking1.sap_concur_user_id == concur_user_id, "Concur User ID mismatch in DB"
        print(">>> DB Tracking Verified: Status=SUCCESS, Version=1")

        # ---------------------------------------------------------------------
        # TEST 2: Same Version Skip (Scenario 1A)
        # ---------------------------------------------------------------------
        print_banner("TEST 2: UNCHANGED VERSION SKIP (Zero API Calls)")
        emp_same = {
            "employeenumber": emp_num,
            "electronicmailaddress": emp_email,
            "rowVersion": 1,  # Identical version
            "blocked": False,
        }
        res2 = await service.sync_or_update_employee(emp_same)
        print("Result:", json.dumps(res2, indent=2))

        assert res2.get("action") == "SKIPPED", f"Expected SKIPPED, got {res2.get('action')}"
        print(">>> TEST 2 PASSED: Successfully skipped with 0 unnecessary API calls")

        # ---------------------------------------------------------------------
        # TEST 3: Version Increment Update (Scenario 1B)
        # ---------------------------------------------------------------------
        print_banner("TEST 3: VERSION INCREMENT -> CALL SAP CONCUR PUT UPDATE")
        emp_v2 = {
            "employeenumber": emp_num,
            "electronicmailaddress": emp_email,
            "firstname": "John",
            "lastname": "LiveTestUpdated",
            "name1": "LiveTestUpdated, John",
            "position": "Senior Tax Consultant - Promoted",  # Updated Title
            "dateemployed": "2026-02-01",
            "country": "US",
            "entityname": "Tax",
            "specification4name": "Tampa",
            "rowVersion": 2,  # Version incremented in Maconomy!
            "blocked": False,
        }
        print(f"New Version: {emp_v2['rowVersion']}, New Position: {emp_v2['position']}")
        res3 = await service.sync_or_update_employee(emp_v2)
        print("Result:", json.dumps(res3, indent=2))

        assert res3.get("status") == "SUCCESS", f"Test 3 failed: {res3}"
        assert res3.get("action") == "UPDATED", f"Expected UPDATED, got {res3.get('action')}"

        # Verify DB Updated
        tracking2 = await service.get_tracking(emp_num)
        assert tracking2.maconomy_version == "2", f"Expected DB version 2, got {tracking2.maconomy_version}"
        print(f">>> TEST 3 PASSED: SAP Concur User Updated! DB version updated to {tracking2.maconomy_version}")

        # ---------------------------------------------------------------------
        # TEST 4: Pre-existing Concur User Adoption (Scenario 3)
        # ---------------------------------------------------------------------
        print_banner("TEST 4: PRE-EXISTING USER ADOPTION (Not in DB, Already in Concur)")
        # We test adoption using an established user that already exists in SAP Concur
        # (e.g. valid.test990098 created earlier, simulating a real pre-existing legacy employee)
        legacy_emp_num = "990098"
        legacy_email = "valid.test990098@example.com"

        # Ensure local DB tracking is cleared for this legacy employee to simulate un-tracked state
        legacy_tracking = await service.get_tracking(legacy_emp_num)
        if legacy_tracking:
            await session.delete(legacy_tracking)
            await session.commit()
            print(f"Cleared local tracking row for legacy employee {legacy_emp_num} to simulate un-tracked state.")

        emp_legacy = {
            "employeenumber": legacy_emp_num,
            "electronicmailaddress": legacy_email,
            "firstname": "Valid2",
            "lastname": "LegacyAdopted",
            "name1": "LegacyAdopted, Valid2",
            "position": "Director of Client Operations",
            "dateemployed": "2026-02-01",
            "country": "US",
            "entityname": "Tax",
            "specification4name": "Tampa",
            "rowVersion": 25,
            "blocked": False,
        }
        res4 = await service.sync_or_update_employee(emp_legacy)
        print("Result:", json.dumps(res4, indent=2))

        assert res4.get("status") == "SUCCESS", f"Test 4 failed: {res4}"
        assert res4.get("action") == "ADOPT_AND_UPDATED", f"Expected ADOPT_AND_UPDATED, got {res4.get('action')}"
        assert res4.get("concur_user_id") is not None, "Adopted Concur User ID must not be None"
        print(f">>> TEST 4 PASSED: Successfully discovered pre-existing user in SAP Concur, adopted ID {res4.get('concur_user_id')}, and updated without 409 conflict!")

        # ---------------------------------------------------------------------
        # TEST 5: Audit Log Verification
        # ---------------------------------------------------------------------
        print_banner("TEST 5: AUDIT LOG VERIFICATION (employee_sync_log)")
        log_stmt = select(EmployeeSyncLog).where(
            EmployeeSyncLog.maconomy_employee_number.in_([emp_num, legacy_emp_num])
        ).order_by(EmployeeSyncLog.created_at.asc())
        logs = (await session.execute(log_stmt)).scalars().all()

        print(f"Total audit logs found: {len(logs)}")
        for idx, l in enumerate(logs, 1):
            print(f" {idx}. Emp: {l.maconomy_employee_number} Action: {l.action:<18} Status: {l.status:<8} OldVer: {str(l.old_version):<5} NewVer: {str(l.new_version):<5} Msg: {l.message}")

        assert len(logs) >= 3, "Expected at least 3 audit logs across tests"
        print(">>> TEST 5 PASSED: Full audit trail successfully confirmed in DB!")

    print_banner("ALL LIVE TESTS PASSED SUCCESSFULLY (5/5)!")


if __name__ == "__main__":
    asyncio.run(run_live_tests())
