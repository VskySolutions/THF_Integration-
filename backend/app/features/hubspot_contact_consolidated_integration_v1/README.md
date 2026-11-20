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
without stopping other confirmed customers. Each v1 bulk execution writes a
RUNNING row and final outcome to `hubspot_contact_consolidation_run_logs`.

After the Company phase, the bulk route reads `/contactpersons/filter` using
the same reconnect token. It selects contact persons with a company number and
email that were created or changed yesterday or today, then uses `remark5` and
`versionnumber` to return new and updated contacts under `contact_persons`.
It also reads contacts of newly created customers and back-queries full email
groups without a date restriction. A consistent existing `remark4` selects the
master; otherwise v1 elects the lowest Contact Person number. Conflicting
nonempty `remark4` values leave a group unresolved so existing stamps are not
overwritten. Only selected masters are upserted to HubSpot. The Contact payload
maps `whos_pd` from available initials in last, middle, first order; without a
last name it uses first, middle order (`Prasad R` becomes `PR`). After a
confirmed master upsert, v1 stamps empty `remark4` fields on the master and
children in that group. Groups with an unchanged known master can stamp empty
members without another HubSpot upsert. It then writes `remark5` as the freshly
bound `versionnumber + 1` for the confirmed master and for children that were
changed or stamped. Stamp or checkpoint failures remain per-record errors.
For groups containing a created or updated Maconomy Contact Person, v1 collects
Company numbers from the MASTER and all children. It resolves the MASTER and Companies
in HubSpot, reads existing Company links, and adds only missing links. Existing
HubSpot associations are preserved. If a parent Company is absent from HubSpot,
v1 fetches its Customer card from Maconomy without the date filter, maps and
upserts it using the Company flow, and writes `customerremark26` after HubSpot
confirms the Company. It then adds the Contact association. If a required link
cannot be added, the group's `remark5` checkpoint waits so a later run can retry.
Contact errors are
reported alongside the Company result. `new_master_contact_ids` identifies confirmed
masters whose Maconomy `remark5` was empty before this run; this does not prove
HubSpot created a new Contact.

Maconomy and HubSpot failures carry stage or reason, upstream HTTP status, and
safe context for troubleshooting. The API returns a safe 502 message for a
failed request without credentials or token details.

The v1 Company route supports manual retry by Maconomy Customer number. It
upserts that Customer regardless of the bulk date window or synced version,
loads all of its Contact Persons, resolves each full email group to its MASTER,
upserts those masters, adds missing links to the requested Company only, and
writes back Contact and Customer checkpoints. Contact writebacks are limited to
the requested Company's Contact Persons and any MASTER upserted by this retry.
The Contact-only retry route remains unimplemented. The scheduler retains the
unversioned bulk path. The existing routes use `/hubspot-consolidated_v0`.

The IT monitoring screen reads the shared run-log table. V1 log details contain
Maconomy record numbers, phase counts, safe error codes and statuses, group
member numbers, and Contact-to-Company pair outcomes. Names, email addresses,
phone numbers, addresses, and upstream response messages are not stored in the
run-log JSON. The monitoring screen's retry button starts the v1 Company flow;
Contact-only retry will be added separately.
