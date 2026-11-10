"""Live test script to test creating a Specification 5 record directly in Deltek Maconomy.

Usage:
    cd backend
    python tests/live_test_create_spec5.py [employee_number] [first_name] [last_name]

Example:
    python tests/live_test_create_spec5.py 99999 John Doe
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# Load .env file
from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(env_path)

from app.core.config import get_settings
from app.features.paycor_integration.services.maconomy_specification5_service import (
    MaconomySpecification5Service,
    MaconomySpecification5ServiceError,
)


async def main() -> None:
    settings = get_settings()

    # CLI args or test defaults
    emp_num = sys.argv[1] if len(sys.argv) > 1 else "TEST8888"
    first_name = sys.argv[2] if len(sys.argv) > 2 else "Test"
    last_name = sys.argv[3] if len(sys.argv) > 3 else "Employee"
    description = f"{last_name}, {first_name}"

    print("=" * 65)
    print("LIVE TEST: MACONOMY SPECIFICATION 5 CREATION")
    print("=" * 65)
    print(f"Target Maconomy URL : {settings.maconomy_url}")
    print(f"Database Shortname  : {settings.maconomy_shortname}")
    print(f"Username            : {settings.maconomy_username}")
    print(f"Employee Number     : {emp_num}")
    print(f"Description         : {description}")
    print("=" * 65)
    print("Sending live request to Maconomy...")

    service = MaconomySpecification5Service()

    try:
        response_record = await service.create_specification5(
            employee_number=emp_num,
            description=description,
        )

        print("\nSUCCESS! Record created in Deltek Maconomy!")
        print("Response data:")
        print(json.dumps(response_record, indent=2))
        print("\nYou can now open Deltek Maconomy and search for:", emp_num)

    except MaconomySpecification5ServiceError as exc:
        print(f"\nERROR: Failed to create record in Maconomy:\n{exc}")
    except Exception as exc:
        print(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())

