# HubSpot contact consolidated integration v1

This folder is the scaffold for the new batch flow. Add the implementation
here incrementally as each step is defined.

The three v1 endpoints are registered with the same API key and active
integration service checks as v0:

- `POST /api/v1/hubspot-consolidated/sync/customers`
- `POST /api/v1/hubspot-consolidated/companies/{maconomy_customer_number}/sync`
- `POST /api/v1/hubspot-consolidated/contacts/{maconomy_contact_person_number}/sync`

They return 501 until their flows are implemented. The scheduler retains the
unversioned batch path. The existing routes use `/hubspot-consolidated_v0`.
