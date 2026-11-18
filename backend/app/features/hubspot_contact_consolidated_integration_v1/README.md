# HubSpot contact consolidated integration v1

This folder contains the v1 integration, built incrementally.

The three v1 endpoints are registered with the same API key and active
integration service checks as v0:

- `POST /api/v1/hubspot-consolidated/sync/customers`
- `POST /api/v1/hubspot-consolidated/companies/{maconomy_customer_number}/sync`
- `POST /api/v1/hubspot-consolidated/contacts/{maconomy_contact_person_number}/sync`

The bulk route authenticates with Maconomy once per request, caches its
X-Reconnect token, and reads active customer cards created or changed yesterday
or today. It classifies new and updated customers with `customerremark26` and
`versionnumber`. The Maconomy customer filter requests at most 5,000 records,
matching v0. It loads Specification 1 and Specification 6 descriptions when
selected customers have the corresponding names.

The v1 Company mapper creates batch upsert inputs keyed by
`maconomy_customer_number`. It retains the Specification 1 description lookup,
but the HubSpot `industry` mapping currently resolves to `None` until verified
option values are supplied. Unmapped `industry` is omitted from the upsert
payload. The mapper sends the Specification 6 description directly as
`line_of_business` when one is available. The HubSpot service sends batches of
100 using the configured service key, retries HTTP 429 up to three attempts, and
returns only confirmed Company IDs. The bulk response includes the selected
Maconomy customers, confirmed Company IDs, and per-record or batch errors.
HubSpot validation messages,
nested error codes, and property names are kept (with messages capped at 1,000
characters) to make partial failures diagnosable.
For each confirmed HubSpot Company, v1 binds the Maconomy customer card, writes
`customerremark26` to the bound `versionnumber + 1`, and reads the card back to
verify the checkpoint. A version conflict is rebound and retried once.
Writeback failures are reported per customer under `maconomy.writeback_errors`
without stopping other confirmed customers. Database run logging is not yet
implemented.

After the Company phase, the bulk route reads `/contactpersons/filter` using
the same reconnect token. It selects contact persons with a company number and
email that were created or changed yesterday or today, then uses `remark5` and
`versionnumber` to return new and updated contacts under `contact_persons`.
This step only discovers contacts; it does not upsert or write them back.
Contact discovery failures are reported alongside the completed Company result.

Maconomy and HubSpot failures carry stage or reason, upstream HTTP status, and
safe context for troubleshooting. The API returns a safe 502 message for a
failed request without credentials or token details.

Company and contact routes still return 501. The scheduler retains the
unversioned bulk path. The existing routes use `/hubspot-consolidated_v0`.
