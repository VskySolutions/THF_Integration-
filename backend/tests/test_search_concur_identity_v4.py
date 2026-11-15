"""Live test script to test SAP Concur Identity v4 Users endpoint with filter query parameter.

Target endpoint requested:
    GET https://us2.api.concursolutions.com/profile/identity/v4/Users?filter=userName eq "afinamore@performltd.com"

Usage:
    cd backend
    python tests/test_search_concur_identity_v4.py
    python tests/test_search_concur_identity_v4.py "afinamore@performltd.com"
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

# ── Path setup ──────────────────────────────────────────────────────────────
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

import httpx
from app.core.config import get_settings


# ── Token helper ─────────────────────────────────────────────────────────────
async def get_access_token(client: httpx.AsyncClient, settings) -> str:
    base_url = str(settings.sap_concur_api_base_url).rstrip("/")
    token_url = f"{base_url}/oauth2/v0/token"

    print(f"\n  [🔐 AUTH] Fetching SAP Concur access token...")
    resp = await client.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": settings.sap_concur_client_id.get_secret_value(),
            "client_secret": settings.sap_concur_client_secret.get_secret_value(),
            "grant_type": "refresh_token",
            "refresh_token": settings.sap_concur_refresh_token.get_secret_value(),
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    print(f"    Token: {token[:30]}... ✅ (Expires in: {payload.get('expires_in', 3600)}s)")
    return token


# ── Main test ─────────────────────────────────────────────────────────────────
async def main() -> None:
    settings = get_settings()

    target_email = sys.argv[1] if len(sys.argv) > 1 else "afinamore@performltd.com"

    print("\n" + "=" * 70)
    print("  TEST: SAP CONCUR IDENTITY v4 USERS QUERY")
    print(f"  Target User Email : {target_email}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Authentication
        try:
            token = await get_access_token(client, settings)
        except Exception as exc:
            print(f"\n  [❌ AUTH FAILED] {exc}")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, application/scim+json",
        }

        # Step 2: Test the exact requested endpoint:
        # GET https://us2.api.concursolutions.com/profile/identity/v4/Users?filter=userName eq "..."
        raw_filter = f'userName eq "{target_email}"'
        encoded_filter = quote(raw_filter, safe="")
        
        test_urls = [
            ("GET /profile/identity/v4/Users (exact requested email)", 
             f"https://us2.api.concursolutions.com/profile/identity/v4/Users?filter={encoded_filter}"),
            ("GET /profile/identity/v4/Users (with .uat suffix)", 
             f"https://us2.api.concursolutions.com/profile/identity/v4/Users?filter={quote(f'userName eq \"{target_email}.uat\"', safe='')}"),
        ]

        for label, url in test_urls:
            print("\n" + "-" * 70)
            print(f"  [📡 TESTING] {label}")
            print(f"  URL: {url}")

            try:
                t0 = time.perf_counter()
                resp = await client.get(url, headers=headers)
                elapsed = time.perf_counter() - t0
                print(f"  Status Code: {resp.status_code} ({elapsed:.2f}s)")
                
                try:
                    data = resp.json()
                    resources = data.get("Resources", [])
                    total = data.get("totalResults", len(resources))
                    print(f"  👉 Total Found: {total}")
                    if resources:
                        for u in resources:
                            print(f"     ✅ User ID     : {u.get('id')}")
                            print(f"        userName    : {u.get('userName')}")
                            print(f"        displayName : {u.get('displayName')}")
                            print(f"        active      : {u.get('active')}")
                            enterprise = u.get("urn:ietf:params:scim:schemas:extension:enterprise:2.0:User", {})
                            if enterprise:
                                print(f"        empNumber   : {enterprise.get('employeeNumber')}")
                                print(f"        department  : {enterprise.get('department')}")
                    else:
                        print(f"     ❌ No user found matching this exact filter")
                except Exception:
                    print("  Response Text:")
                    print(resp.text[:500])

            except Exception as exc:
                print(f"  Request Error: {exc}")

    print("\n" + "=" * 70)
    print("  TEST COMPLETED")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
