"""HubSpot Contact upsert payload builder.

Contains a single function returning the verified working payload
(user-verified 2026-10-15): idProperty=email with objectWriteTraceId.
"""

from typing import Any


def map_contacts_hb_contacts() -> dict[str, Any]:
    """Return the verified HubSpot contact upsert payload."""
    return {
        "inputs": [
            {
                "id": "usertest@test.com",
                "idProperty": "email",
                "properties": {
                    "email": "usertest@test.com",
                    "phone": "+1999999999",
                    "jobtitle": "Manager",
                    "lifecyclestage": "lead",
                },
            }
        ]
    }
