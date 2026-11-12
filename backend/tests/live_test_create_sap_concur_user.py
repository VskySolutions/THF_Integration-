"""Live test script to test creating an employee in SAP Concur directly.

Usage:
    cd backend
    python tests/live_test_create_sap_concur_user.py [employee_number] [email] [first_name] [last_name]

Example:
    python tests/live_test_create_sap_concur_user.py 222222 vskytest@example.com Sarvesh Test
"""

import asyncio
import json
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(env_path)

from app.core.config import get_settings
from app.features.sap_concur_employee_integration.services.sap_concur_service import (
    SAPConcurEmployeeService,
    SAPConcurEmployeeServiceError,
)


async def main() -> None:
    settings = get_settings()

    emp_num = sys.argv[1] if len(sys.argv) > 1 else "TEST7777"
    email = sys.argv[2] if len(sys.argv) > 2 else "test.employee7777@example.com"
    first_name = sys.argv[3] if len(sys.argv) > 3 else "Test"
    last_name = sys.argv[4] if len(sys.argv) > 4 else "Employee"

    # Simulate the exact Maconomy created_employee dictionary format
    sample_maconomy_employee = {
        "employeenumber": emp_num,
        "electronicmailaddress": email,
        "firstname": first_name,
        "lastname": last_name,
        "name1": f"{last_name}, {first_name}",
        "dateemployed": "2026-01-01",
        "country": "US",
        "entityname": "100",
        "position": "Staff Accountant",
        "blocked": False,
        "phone": "555-123-4567",
        "zipcode": "10001",
        "postaldistrict": "New York",
        "name2": "123 Business Way",
    }

    print("=" * 65)
    print("LIVE TEST: SAP CONCUR USER CREATION")
    print("=" * 65)
    base_url = str(settings.sap_concur_api_base_url).rstrip('/')
    print(f"Target Base URL    : {base_url}")
    print(f"Target SCIM URL    : {base_url}/profile/v4/Bulk/")
    print(f"Employee Number    : {emp_num}")
    print(f"Email (Login/User) : {email}")
    print(f"Name               : {first_name} {last_name}")
    print("=" * 65)
    print("Sending live SCIM request to SAP Concur...")

    service = SAPConcurEmployeeService()

    try:
        response = await service.create_employee(sample_maconomy_employee)
        print("\nRESPONSE FROM SAP CONCUR:")
        print(json.dumps(response, indent=2))

        created_count = response.get("created", 0)
        if created_count > 0:
            print("\nSUCCESS! User created in SAP Concur!")
        else:
            print("\nNote: Request completed, check details above for status.")

    except SAPConcurEmployeeServiceError as exc:
        print(f"\nERROR: SAP Concur service error:\n{exc}")
    except Exception as exc:
        print(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
