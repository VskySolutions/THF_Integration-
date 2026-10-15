"""HubSpot Company upsert payload builder.

Contains a single function returning the verified working payload
(user-verified 2026-10-15): idProperty=maconomy_customer_number.
"""

from typing import Any


def map_customers_company() -> dict[str, Any]:
    """Return the verified HubSpot company upsert payload."""
    return {
        "inputs": [
            {
                "idProperty": "maconomy_customer_number",
                "id": "9999",
                "properties": {
                    "name": "VskyTest",
                    "domain": "1234test.com",
                    "city": "Cambridge",
                    "phone": "555-555-555",
                    "state": "Massachusetts",
                    "maconomy_customer_number": "9999",
                },
            }
        ]
    }
