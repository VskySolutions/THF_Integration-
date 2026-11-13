"""Live integration test suite for SAP Concur User creation from Maconomy Employee data.

Tests the live SAP Concur SCIM 2.0 API with authentication, token caching,
and static test cases covering:
  Case 1: Standard Employee with Full Details (15 confirmed fields + 9 constants)
  Case 2: Minimal Employee (only mandatory fields: email, employeenumber, name)
  Case 3: Blocked / Inactive Employee (active = false)
  Case 4: Approver / Manager Link (superioremployee)
  Case 5: Validation Guard: Missing Email (expected EmployeeMappingError, no API call)
  Case 6: Validation Guard: Missing Employee Number (expected EmployeeMappingError, no API call)

Usage:
    cd backend
    python tests/live_test_sap_concur_employee_suite.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(env_path)

from app.core.config import get_settings
from app.features.sap_concur_employee_integration.mappers.employee_mapper import (
    EmployeeMappingError,
    map_maconomy_employee_to_scim_user,
)
from app.features.sap_concur_employee_integration.services.sap_concur_service import (
    SAPConcurEmployeeService,
    SAPConcurEmployeeServiceError,
)


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


async def run_live_test_cases() -> None:
    settings = get_settings()
    base_url = str(settings.sap_concur_api_base_url).rstrip("/")

    print_header("LIVE SAP CONCUR SCIM 2.0 INTEGRATION TEST SUITE")
    print(f"Target SAP Concur Base URL : {base_url}")
    print(f"Target Bulk SCIM Endpoint  : {base_url}/profile/v4/Bulk/")
    print(f"Client ID Configured       : {settings.sap_concur_client_id.get_secret_value()[:6]}***")
    print(f"Refresh Token Configured   : {settings.sap_concur_refresh_token.get_secret_value()[:6]}***")

    service = SAPConcurEmployeeService()

    # =========================================================================
    # TEST CASE 1: Standard Employee with Full Details
    # =========================================================================
    print_header("TEST CASE 1: Standard Employee with Full Confirmed Details")
    tc1_data = {
        "employeenumber": "990001",
        "electronicmailaddress": "john.concur.test990001@example.com",
        "firstname": "John",
        "middlename": "A",
        "lastname": "Doe",
        "name1": "Doe, John A",
        "position": "Senior Tax Consultant",
        "dateemployed": "2026-02-01",
        "country": "US",
        "entityname": "Tax",
        "specification4name": "Tampa",
        "phone": "555-019-2831",
        "name2": "742 Evergreen Terrace",
        "postaldistrict": "Tampa",
        "zipcode": "33601",
        "blocked": False,
        "superioremployee": "100001",
    }
    print("Input Maconomy Data:")
    print(json.dumps(tc1_data, indent=2))

    scim_tc1 = map_maconomy_employee_to_scim_user(tc1_data)
    print("\nGenerated SCIM User Payload (verified mappings):")
    print(json.dumps(scim_tc1, indent=2))

    try:
        print("\nSending live request to SAP Concur...")
        res1 = await service.create_employee(tc1_data)
        print("Live Response:")
        print(json.dumps(res1, indent=2))
        assert res1.get("created", 0) > 0, "Expected created > 0"
        print(">>> RESULT: TEST CASE 1 PASSED (Accepted by SAP Concur)")
    except Exception as exc:
        print(f">>> RESULT: TEST CASE 1 FAILED: {exc}")

    # =========================================================================
    # TEST CASE 2: Minimal Mandatory Fields Only
    # =========================================================================
    print_header("TEST CASE 2: Minimal Employee (Only Email, Number, Name)")
    tc2_data = {
        "employeenumber": "990002",
        "electronicmailaddress": "jane.minimal.test990002@example.com",
        "firstname": "Jane",
        "lastname": "Smith",
        "name1": "Smith, Jane",
        "blocked": False,
    }
    try:
        scim_tc2 = map_maconomy_employee_to_scim_user(tc2_data)
        print("Generated Minimal SCIM Payload:")
        print(json.dumps(scim_tc2, indent=2))
        print("\nSending live request to SAP Concur...")
        res2 = await service.create_employee(tc2_data)
        print("Live Response:")
        print(json.dumps(res2, indent=2))
        assert res2.get("created", 0) > 0, "Expected created > 0"
        print(">>> RESULT: TEST CASE 2 PASSED (Accepted by SAP Concur)")
    except Exception as exc:
        print(f">>> RESULT: TEST CASE 2 FAILED: {exc}")

    # =========================================================================
    # TEST CASE 3: Inactive / Blocked Employee (active = False)
    # =========================================================================
    print_header("TEST CASE 3: Blocked Employee (active=False)")
    tc3_data = {
        "employeenumber": "990003",
        "electronicmailaddress": "bob.inactive.test990003@example.com",
        "firstname": "Bob",
        "lastname": "Blocked",
        "blocked": True,
    }
    try:
        scim_tc3 = map_maconomy_employee_to_scim_user(tc3_data)
        print(f"Generated Payload 'active' flag: {scim_tc3.get('active')}")
        assert scim_tc3.get("active") is False, "Expected active to be False"
        print("\nSending live request to SAP Concur...")
        res3 = await service.create_employee(tc3_data)
        print("Live Response:")
        print(json.dumps(res3, indent=2))
        assert res3.get("created", 0) > 0, "Expected created > 0"
        print(">>> RESULT: TEST CASE 3 PASSED (Accepted by SAP Concur)")
    except Exception as exc:
        print(f">>> RESULT: TEST CASE 3 FAILED: {exc}")

    # =========================================================================
    # TEST CASE 4: Supervisor / Approver Hierarchy
    # =========================================================================
    print_header("TEST CASE 4: Supervisor Hierarchy Extension")
    tc4_data = {
        "employeenumber": "990004",
        "electronicmailaddress": "alex.approver.test990004@example.com",
        "firstname": "Alex",
        "lastname": "Junior",
        "superioremployee": "100081",
        "blocked": False,
    }
    try:
        scim_tc4 = map_maconomy_employee_to_scim_user(tc4_data)
        approver_ext = scim_tc4.get("urn:ietf:params:scim:schemas:extension:spend:2.0:Approver")
        travel_ext = scim_tc4.get("urn:ietf:params:scim:schemas:extension:travel:2.0:User")
        print("Spend Approver Extension:")
        print(json.dumps(approver_ext, indent=2))
        print("Travel Manager Extension:")
        print(json.dumps(travel_ext, indent=2))
        assert approver_ext is not None, "Expected spend approver extension"
        assert travel_ext.get("manager", {}).get("employeeNumber") == "100081"
        print("\nSending live request to SAP Concur...")
        res4 = await service.create_employee(tc4_data)
        print("Live Response:")
        print(json.dumps(res4, indent=2))
        assert res4.get("created", 0) > 0, "Expected created > 0"
        print(">>> RESULT: TEST CASE 4 PASSED (Accepted by SAP Concur)")
    except Exception as exc:
        print(f">>> RESULT: TEST CASE 4 FAILED: {exc}")

    # =========================================================================
    # TEST CASE 5: Validation Guard: Missing Email (Negative Test)
    # =========================================================================
    print_header("TEST CASE 5 (Negative): Missing Email Validation Guard")
    tc5_data = {
        "employeenumber": "990005",
        "electronicmailaddress": "",  # Missing email
        "firstname": "No",
        "lastname": "Email",
    }
    try:
        map_maconomy_employee_to_scim_user(tc5_data)
        print(">>> RESULT: TEST CASE 5 FAILED: Expected EmployeeMappingError not raised")
    except EmployeeMappingError as exc:
        print(f"Successfully caught expected validation error: {exc}")
        print(">>> RESULT: TEST CASE 5 PASSED (Guarded, no invalid request sent to Concur)")

    # =========================================================================
    # TEST CASE 6: Validation Guard: Missing Employee Number (Negative Test)
    # =========================================================================
    print_header("TEST CASE 6 (Negative): Missing Employee Number Validation Guard")
    tc6_data = {
        "employeenumber": None,  # Missing employee number
        "electronicmailaddress": "valid.email@example.com",
        "firstname": "No",
        "lastname": "Number",
    }
    try:
        map_maconomy_employee_to_scim_user(tc6_data)
        print(">>> RESULT: TEST CASE 6 FAILED: Expected EmployeeMappingError not raised")
    except EmployeeMappingError as exc:
        print(f"Successfully caught expected validation error: {exc}")
        print(">>> RESULT: TEST CASE 6 PASSED (Guarded, no invalid request sent to Concur)")

    print_header("ALL TEST CASES EXECUTED")


if __name__ == "__main__":
    asyncio.run(run_live_test_cases())

