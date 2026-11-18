# HubSpot contact consolidated integration v1

This folder contains the v1 integration, built incrementally.

The three v1 endpoints are registered with the same API key and active
integration service checks as v0:

- `POST /api/v1/hubspot-consolidated/sync/customers`
- `POST /api/v1/hubspot-consolidated/companies/{maconomy_customer_number}/sync`
- `POST /api/v1/hubspot-consolidated/contacts/{maconomy_contact_person_number}/sync`

The bulk route now authenticates with Maconomy once per request, caches its
X-Reconnect token for later calls in that run, and reads active customer cards
created or changed yesterday or today. It returns only the customer records
classified as new or updated by `customerremark26` and `versionnumber`, grouped
under `new_customers` and `updated_customers`. The Maconomy filter currently
requests at most 5,000 records, matching v0. No HubSpot writes or run logging
occur in this discovery step.
Maconomy failures carry a stage, reason, and upstream HTTP status in the v1
exception and are logged with the request ID and chained traceback. The API
returns a safe 502 message without credentials or token details.

Company and contact routes still return 501. The scheduler retains the
unversioned bulk path. The existing routes use `/hubspot-consolidated_v0`.
