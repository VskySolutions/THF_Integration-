"""Live test: Single SAP Concur user creation via POST /profile/v4/Users
(NOT bulk) using companyId and dummy employee payload.

Reads credentials directly from backend/.env

Usage:
    cd backend
    python tests/test_single_sap_concur_create.py
    python tests/test_single_sap_concur_create.py 999001 testuser@thf.com John Doe
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

import httpx
from app.core.config import get_settings

# ── Constants ────────────────────────────────────────────────────────────────
COMPANY_ID       = "f7255b65-38e0-458f-ab3d-40856e011c0b"   # THF Concur sandbox
TOKEN_PATH       = "/oauth2/v0/token"
CREATE_USER_PATH = "/profile/v4/Users"
SCIM_CONTENT     = "application/scim+json"
TOKEN_CONTENT    = "application/x-www-form-urlencoded"

SCIM_USER_SCHEMA       = "urn:ietf:params:scim:schemas:core:2.0:User"
ENTERPRISE_USER_SCHEMA = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
SPEND_USER_SCHEMA      = "urn:ietf:params:scim:schemas:extension:spend:2.0:User"
TRAVEL_USER_SCHEMA     = "urn:ietf:params:scim:schemas:extension:travel:2.0:User"


# ── Token helper ─────────────────────────────────────────────────────────────
async def get_access_token(client: httpx.AsyncClient, settings) -> str:
    base_url  = str(settings.sap_concur_api_base_url).rstrip("/")
    token_url = f"{base_url}{TOKEN_PATH}"

    print(f"\n  [🔐 AUTH] Fetching SAP Concur access token (following sap_concur_integration)...")
    print(f"    Token URL   : {token_url}")

    resp = await client.post(
        token_url,
        headers={"Content-Type": TOKEN_CONTENT},
        data={
            "client_id":     settings.sap_concur_client_id.get_secret_value(),
            "client_secret": settings.sap_concur_client_secret.get_secret_value(),
            "grant_type":    "refresh_token",
            "refresh_token": settings.sap_concur_refresh_token.get_secret_value(),
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    expires_in = payload.get("expires_in", 3600)
    print(f"    Token       : {token[:30]}...  ✅ (Expires in: {expires_in}s)")



    
    return token


# ── Build SCIM payload ────────────────────────────────────────────────────────
def build_scim_payload(emp_num: str, email: str, first_name: str, last_name: str) -> dict:
    payload = {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": email,
        "active": True,
        "name": {
            "givenName":  first_name,
            "familyName": last_name,
        },
        "emails": [{"type": "work", "value": email}],
        "preferredLanguage": "en-US",
        "title": "Test Engineer",
        "entitlements": ["Expense"],
        ENTERPRISE_USER_SCHEMA: {
            "employeeNumber": emp_num,
            "companyId":      COMPANY_ID,
            "department":     "Engineering",
            "startDate":      "2024-01-15T00:00:00Z",
        },
        SPEND_USER_SCHEMA: {
            "locale":                "en-US",
            "ledgerCode":            "DELTEK",
            "reimbursementCurrency": "USD",
            "reimbursementType":     "CONCUR_PAY",
            "country":               "US",
        },
        "addresses": [
            {
                "type":          "home",
                "streetAddress": "123 Test Street",
                "locality":      "Tampa",
                "postalCode":    "33601",
                "country":       "US",
            }
        ],
    }

    print(f"\n  [📋 PAYLOAD] SCIM Payload Summary")
    print(f"    userName        : {payload['userName']}")
    print(f"    Employee Number : {payload[ENTERPRISE_USER_SCHEMA]['employeeNumber']}")
    print(f"    Name            : {payload['name']}")
    print(f"    Active          : {payload['active']}")
    print(f"    Company ID      : {payload[ENTERPRISE_USER_SCHEMA]['companyId']}")
    print(f"    Start Date      : {payload[ENTERPRISE_USER_SCHEMA]['startDate']}")
    print(f"    Department      : {payload[ENTERPRISE_USER_SCHEMA]['department']}")
    print(f"    Reimburse Type  : {payload[SPEND_USER_SCHEMA]['reimbursementType']}")
    print(f"    Entitlements    : {payload['entitlements']}")

    return payload


# ── Main test ─────────────────────────────────────────────────────────────────
async def main() -> None:
    settings = get_settings()

    # CLI args or defaults
    emp_num    = sys.argv[1] if len(sys.argv) > 1 else "TEST_SINGLE_001"
    email      = sys.argv[2] if len(sys.argv) > 2 else "test.single.001@thf-test.com"
    first_name = sys.argv[3] if len(sys.argv) > 3 else "SingleTest"
    last_name  = sys.argv[4] if len(sys.argv) > 4 else "UserOne"

    base_url   = str(settings.sap_concur_api_base_url).rstrip("/")
    create_url = f"{base_url}{CREATE_USER_PATH}"

    print("\n" + "=" * 65)
    print("  LIVE TEST: SAP CONCUR SINGLE USER CREATION")
    print("  Endpoint: POST /profile/v4/Users  (NOT Bulk)")
    print("=" * 65)
    print(f"  Base URL        : {base_url}")
    print(f"  Create URL      : {create_url}")
    print(f"  Employee Number : {emp_num}")
    print(f"  Email           : {email}")
    print(f"  Name            : {first_name} {last_name}")
    print(f"  Company ID      : {COMPANY_ID}")
    print("=" * 65)

    payload = build_scim_payload(emp_num, email, first_name, last_name)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Auth
        try:
            token = await get_access_token(client, settings)
        except Exception as exc:
            print(f"\n  [❌ AUTH FAILED] {exc}")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  SCIM_CONTENT,
            "Accept":        SCIM_CONTENT,
        }

        # Step 2: Create user
        print(f"\n  [🚀 REQUEST] POST {create_url}")
        t_start = time.perf_counter()
        resp = await client.post(create_url, headers=headers, json=payload)
        print(resp.text)
        elapsed = time.perf_counter() - t_start

        print(f"  [📡 RESPONSE] HTTP {resp.status_code}  ({elapsed:.2f}s)")
        print("-" * 65)

        try:
            result = resp.json()
            print(json.dumps(result, indent=2))
        except Exception:
            print(resp.text)

        print("-" * 65)

        # Step 3: Interpret result
        if resp.status_code in (200, 201, 202):
            user_id = result.get("id") if isinstance(result, dict) else None
            status_url = result.get("meta", {}).get("statusUrl") if isinstance(result, dict) else None
            print(f"\n  [✅ SUCCESS] SAP Concur user created!")
            print(f"    Concur User ID : {user_id}")
            print(f"    userName       : {result.get('userName') if isinstance(result, dict) else 'N/A'}")
            
            if status_url:
                print(f"\n  [⏳ PROVISION CHECK] Checking provision status in 2s...")
                await asyncio.sleep(2)
                p_resp = await client.get(status_url, headers={"Authorization": f"Bearer {token}"})
                if p_resp.status_code == 200:
                    p_data = p_resp.json()
                    print(f"    Provision Completed : {p_data.get('status', {}).get('completed')}")
                    print(f"    Provision Success   : {p_data.get('status', {}).get('success')}")
                    print(f"    Operations Count    : {p_data.get('operationsCount')}")
                else:
                    print(f"    Provision status check returned HTTP {p_resp.status_code}")
        elif resp.status_code == 409:
            print(f"\n  [⚠️  CONFLICT 409] User already exists in SAP Concur (userName/employeeNumber duplicate)")
        elif resp.status_code == 400:
            print(f"\n  [❌ BAD REQUEST 400] Payload validation failed — check required fields")
        elif resp.status_code in (401, 403):
            print(f"\n  [❌ AUTH ERROR {resp.status_code}] Token invalid or expired — check .env credentials")
        else:
            print(f"\n  [❌ FAILED] HTTP {resp.status_code}")

    print("\n" + "=" * 65)
    print("  TEST COMPLETE")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

