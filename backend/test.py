"""
Test script to verify the dynamic department work location mapping and Maconomy General Journal flow.
"""

import asyncio
import json
from unittest.mock import AsyncMock

from app.features.paycor_payroll_integration.constants import (
    DEFAULT_LEGAL_ENTITY_ID,
    LOCATION_NAME_TO_SHORTFORM,
    STATIC_DEPARTMENT_WORK_LOCATIONS,
)
from app.features.paycor_payroll_integration.mappers.payroll_journal_mapper import (
    group_gl_records_by_department,
    map_paycor_gl_record_to_maconomy_line,
    map_paycor_gl_to_maconomy_card,
)
from app.features.paycor_payroll_integration.services.paycor_payroll_service import (
    PaycorPayrollService,
)
from app.features.paycor_payroll_integration.validators.journal_validator import (
    validate_journal_payload,
)


# 1. Sample Paycor Department API response (from live endpoint schema)
MOCK_PAYCOR_DEPARTMENTS_API_RESPONSE = {
    "hasMoreResults": False,
    "records": [
        {
            "id": "025211eb-e826-0000-0000-00004d6c0200",
            "description": "Consultant Level 2 Tampa GCS",
            "workLocationName": "Tampa",
        },
        {
            "id": "122fc6bb-e25d-0000-0000-00004d6c0200",
            "description": "Director-Panama City CAS",
            "workLocationName": "Panama City",
        },
        {
            "id": "14036cc3-f59d-0000-0000-00004d6c0200",
            "description": "Staff Audit",
            "workLocationName": "Tallahassee",
        },
        {
            "id": "20b3c46e-037b-0000-0000-00004d6c0200",
            "description": "Bainbridge",
            "workLocationName": "Bainbridge",
        },
        {
            "id": "68cdcf54-865b-0000-0000-00004d6c0200",
            "description": "Lakeland",
            "workLocationName": "Lakeland",
        },
        {
            "id": "f8c600e7-f2e5-0000-0000-00004d6c0200",
            "description": "Staff - Dade City",
            "workLocationName": "Dade City",
        },
    ],
}

# 2. Sample Paycor General Ledger Records referencing these departments
MOCK_GL_RECORDS = [
    {
        "departmentId": "025211eb-e826-0000-0000-00004d6c0200",
        "departmentDescription": "CONSULTANT LEVEL 2 TAMPA GCS",
        "debitAmount": 1500.00,
        "creditAmount": 0.0,
        "checkDate": "2026-09-30",
        "description": "Payroll Regular Pay",
        "employeeNumber": "1001",
    },
    {
        "departmentId": "122fc6bb-e25d-0000-0000-00004d6c0200",
        "departmentDescription": "DIRECTOR-PANAMA CITY CAS",
        "debitAmount": 0.0,
        "creditAmount": 850.50,
        "checkDate": "2026-09-30",
        "description": "Tax Withholding",
        "employeeNumber": "1002",
    },
    {
        "departmentId": "14036cc3-f59d-0000-0000-00004d6c0200",
        "departmentDescription": "STAFF AUDIT",
        "debitAmount": -300.00,  # Negative debit: tests auto-reversal to credit
        "creditAmount": 0.0,
        "checkDate": "2026-09-30",
        "description": "Adjustment Expense",
        "employeeNumber": "1003",
    },
    {
        "departmentId": "20b3c46e-037b-0000-0000-00004d6c0200",
        "departmentDescription": "BAINBRIDGE OFFICE",
        "debitAmount": 500.00,
        "creditAmount": 0.0,
        "checkDate": "2026-09-30",
        "description": "Direct Deposit",
        "employeeNumber": "1004",
    },
    {
        "departmentId": "68cdcf54-865b-0000-0000-00004d6c0200",
        "departmentDescription": "LAKELAND TAX",
        "debitAmount": 2200.00,
        "creditAmount": 0.0,
        "checkDate": "2026-09-30",
        "description": "Salary Expense",
        "employeeNumber": "1005",
    },
    {
        "departmentId": "f8c600e7-f2e5-0000-0000-00004d6c0200",
        "departmentDescription": "STAFF - DADE CITY",
        "debitAmount": 750.00,
        "creditAmount": 0.0,
        "checkDate": "2026-09-30",
        "description": "Regular Pay",
        "employeeNumber": "1006",
    },
]


async def run_end_to_end_test():
    print("=" * 80)
    print("STEP 1: Testing Dynamic Paycor Departments API Fetch")
    print("=" * 80)

    service = PaycorPayrollService()
    # Mock the actual HTTP call to Paycor STS and departments endpoint
    service.get_access_token = AsyncMock(return_value="mock-token-xyz")
    service.get_legal_entity_departments = AsyncMock(
        return_value=MOCK_PAYCOR_DEPARTMENTS_API_RESPONSE
    )

    # Call the service method that fetches departments in one shot
    dynamic_work_location_map = (
        await service.get_employee_work_location_lookup(DEFAULT_LEGAL_ENTITY_ID)
    )

    print(f"Total dynamic departments resolved: {len(dynamic_work_location_map)}")
    for dept_id, shortform in dynamic_work_location_map.items():
        static_match = STATIC_DEPARTMENT_WORK_LOCATIONS.get(dept_id, "N/A")
        print(
            f"  - Department [{dept_id[:12]}...] -> Dynamic: '{shortform}' | Static constant: '{static_match}'"
        )
        assert shortform in ["TPA", "PCB", "TLH", "-", "LKL", "DDC"], f"Unexpected shortform: {shortform}"

    print("\n" + "=" * 80)
    print("STEP 2: Grouping GL Records By Department & Mapping to Maconomy Lines")
    print("=" * 80)

    grouped_gl = group_gl_records_by_department(MOCK_GL_RECORDS)
    print(f"Total departments identified in GL records: {len(grouped_gl)}")

    for dept_name, dept_records in grouped_gl.items():
        card_data = map_paycor_gl_to_maconomy_card(
            planner_id="test-planner-dynamic-001",
            group_id="test-group-001",
            run_type="Regular",
            company_number="100",
            department_description=dept_name,
        )

        raw_mapped_lines = [
            map_paycor_gl_record_to_maconomy_line(
                r,
                employee_id_map={},
                department_description=dept_name,
                work_location_map=dynamic_work_location_map,
            )
            for r in dept_records
        ]

        # Zero-amount line suppression filter
        non_zero_lines = [
            line for line in raw_mapped_lines
            if (line.get("debitbase") or 0.0) > 0 or (line.get("creditbase") or 0.0) > 0
        ]

        validation = validate_journal_payload(card_data, non_zero_lines)

        print(f"\n--- Department: '{dept_name}' ---")
        print(f"Should Create Journal: {validation['should_create']}")
        print(f"Lines Count: {validation['lines_count']}")
        print("Card Header:")
        print(" ", json.dumps(validation["card_data"], indent=2))
        print("Journal Line Item:")
        for idx, line in enumerate(validation["lines"], 1):
            print(f"  Line {idx}:")
            print(f"    Account: {line['accountnumber']}")
            print(f"    Entity Code: {line['entityname']}")
            print(f"    Work Location (specification4name): '{line['specification4name']}'")
            print(f"    Debit: {line['debitbase']} | Credit: {line['creditbase']}")
            print(f"    Employee#: {line['employeenumber']}")
            print(f"    Entry Text: {line['entrytext']}")

            # Assert that work location is properly resolved from the dynamic lookup
            expected_dept_id = dept_records[idx - 1]["departmentId"]
            expected_shortform = dynamic_work_location_map[expected_dept_id]
            assert line["specification4name"] == expected_shortform, (
                f"Mismatch in specification4name: expected {expected_shortform}, got {line['specification4name']}"
            )
            # Assert negative debits are properly auto-converted to positive credits
            assert line["debitbase"] >= 0.0, "debitbase must be >= 0"
            assert line["creditbase"] >= 0.0, "creditbase must be >= 0"

    print("\n" + "=" * 80)
    print("STEP 3: Testing Fallback when Paycor Departments API is Down")
    print("=" * 80)
    service.get_legal_entity_departments = AsyncMock(
        side_effect=Exception("Simulated Paycor 500 Network Timeout")
    )
    fallback_map = await service.get_employee_work_location_lookup(DEFAULT_LEGAL_ENTITY_ID)
    assert fallback_map == STATIC_DEPARTMENT_WORK_LOCATIONS, "Should fallback to static map"
    print("SUCCESS: Fallback correctly returns STATIC_DEPARTMENT_WORK_LOCATIONS on failure.")

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED: Dynamic Work Location Mapping is verified and working perfectly!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_end_to_end_test())

