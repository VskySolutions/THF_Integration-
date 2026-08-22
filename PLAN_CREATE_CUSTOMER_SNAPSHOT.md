# Plan: Use the Maconomy Job Customer Snapshot During Creation

## Objective

Update the CaseWare Cloud engagement creation flow so that the single Maconomy job-detail response supplies both job and customer snapshot information.

The create workflow will no longer call the separate Maconomy customer-card API. Entity creation and address creation will continue as before, but both payloads will be built from the job detail returned for the requested `jobnumber`.

This change applies to both create entry points:

- `POST /caseware-cloud/on-create-engagement-post`
- `POST /caseware-cloud/sync-todays-created-maconomy-engagements-with-caseware`

Both endpoints already use the shared `_create_engagement(...)` workflow. The refactor will be made in that shared workflow so direct API creation and daily synchronization behave consistently and neither path performs a separate customer-card lookup.

The existing `cw_addresses` column will remain unchanged. Its address entry will be populated from the job snapshot and enriched with the created CaseWare address CWGuid.

## Maconomy Job Fields

The job-detail container request will include these existing job fields:

- `jobnumber`
- `jobname`
- `template`
- `versionnumber`

It will also include the customer snapshot fields stored on the job:

| Maconomy field | Meaning | Current CaseWare usage |
| --- | --- | --- |
| `customernumber` | Customer number | Available as part of the job snapshot; no separate lookup key is needed |
| `name1` | Client name | CaseWare address `Name` |
| `name2` | Address line 1 | CaseWare address `Address1` |
| `postaldistrict` | City | CaseWare address `City` |
| `country` | Country | CaseWare entity `CountryCode` and address `Country` |

These fields will be requested by `_start_job_lookup(...)`, so `get_job_detail_by_job_number(...)` returns one flat job/customer snapshot.

The daily-created-job filter does not need to return all address fields because that endpoint only takes each candidate's `jobnumber` and then calls the full job-detail workflow.

## Revised Create Workflow

1. Receive a `jobnumber` from either:
   - `POST /caseware-cloud/on-create-engagement-post`.
   - Each candidate returned during `POST /caseware-cloud/sync-todays-created-maconomy-engagements-with-caseware`.
2. Check for an existing entity mapping exactly as today.
3. Fetch the Maconomy job detail once.
4. Preserve the existing errors for:
   - Maconomy request failure.
   - Job not found.
   - Template job.
5. Do not call `get_client_detail_by_customer_number(...)`.
6. Do not add a nested `job_detail["customer"]` object.
7. Pass the flat `job_detail` directly to CaseWare entity creation.
8. Map the CaseWare entity `CountryCode` from `job_detail["country"]`, retaining the existing fallback behavior when country is unavailable.
9. Create the CaseWare entity exactly as in the current workflow.
10. Create the entity mapping with:
    - CaseWare entity CWGuid.
    - Maconomy job number.
    - Maconomy job version number.
11. Pass the same flat `job_detail` directly to CaseWare address creation.
12. The existing address mapper will read:
    - `name1`
    - `name2`
    - `postaldistrict`
    - `country`
13. Parse the address POST response body as the created integer address ID.
14. GET `/api/v2/entities/{entity_cw_guid}/addresses?page=1&pageSize=50` using the same authenticated client.
15. Parse the returned top-level address array and find the object whose `Id` equals the integer address ID returned by POST.
16. Require that matching address object to contain a non-empty `CWGuid`.
17. Preserve the existing behavior when CaseWare entity or address creation fails.
18. Persist `cw_addresses` through the existing `set_mapping_addresses(...)` call.
19. Build the `cw_addresses` entry from the job snapshot and CaseWare address result:
    - `maconomy_customer_number`: `job_detail["customernumber"]`.
    - `cw_address_id`: the CaseWare address ID returned after address creation.
    - `caseware_cw_guid`: the matching address object's `CWGuid` from the entity GET response.
    - `maconomy_customer_version_number`: `job_detail["versionnumber"]`, representing the version of the job-level customer snapshot.
20. Preserve the existing successful create response and success log indicating that the entity and address were created.

## Planned Code Changes

### `services/maconomy_services.py`

- Add `name2`, `postaldistrict`, and `country` to the job card fields in `_start_job_lookup(...)`.
- Keep `customernumber` and `name1` in the job card fields.
- Continue using `get_job_detail_by_job_number(...)` as the single Maconomy request workflow for create.
- Remove the customer-card lookup methods after confirming they have no remaining callers in `caseware_cloud_intergration`:
  - `get_client_detail_by_customer_number(...)`
  - `_start_client_lookup(...)`
  - `_get_client_record(...)`
  - `_clients_url(...)`

The `cch_intergration` package is not part of this change and will not be modified.

### `routers/create_caseware_router.py`

- Apply the change inside the shared `_create_engagement(...)` workflow used by both create endpoints.
- Remove the `_add_customer_detail(...)` call and its separate customer-error branch.
- Remove the `_add_customer_detail(...)` helper.
- Pass `job_detail` directly to `create_entity(...)`.
- Pass `job_detail` directly to `create_entity_address(...)`.
- Keep the call to `set_mapping_addresses(...)`.
- Populate its existing JSON entry from `job_detail` instead of nested customer data.
- Keep mapping creation, CaseWare address creation, error handling, return values, and integration-log behavior otherwise unchanged.

### `mappers/entity_mapper.py`

- Change the creation mapper's `CountryCode` source from `job_data["customer"]["country"]` to the flat `job_data["country"]`.
- Keep all other creation payload fields and behavior unchanged.
- Do not modify the entity-update mapper as part of this work.

### `mappers/address_mapper.py`

- No field-mapping change is expected because it already reads `name1`, `name2`, `postaldistrict`, and `country` from the dictionary it receives.
- Its caller will now pass the flat Maconomy job detail instead of nested customer detail.

### `services/caseware_cloud_service.py`

- Keep the existing address POST request.
- Parse and validate its response body as the numeric address ID.
- Reuse the same authenticated client/token to GET the entity's paginated address collection.
- Validate that the response is a top-level array.
- Find the address object whose `Id` equals the POST response integer.
- Require and return that address object's `CWGuid` together with its `Id`.
- Treat a missing address object or missing/invalid CWGuid as a failed address-creation workflow.

### `models/entity_engagement_mapping.py`

- No change. Keep the existing nullable JSONB `cw_addresses` column.

### `schemas/entity_engagement_mapping.py`

- No change. Keep `cw_addresses` in `EntityEngagementMappingRead`.

### `services/entity_engagement_mapping_service.py`

- No change. Continue using `set_mapping_addresses(...)` to persist the existing JSON structure.

### Alembic migration

- No migration is required because `cw_addresses` remains unchanged.

## Behavior That Must Remain Unchanged

- Duplicate mapping detection and its `409 Conflict` behavior for the direct create API.
- Direct creation through `/on-create-engagement-post`.
- Batch creation through `/sync-todays-created-maconomy-engagements-with-caseware`, including its per-job result handling.
- Job-not-found handling.
- Template rejection.
- CaseWare entity creation endpoint and payload fields other than the `CountryCode` source.
- CaseWare address creation endpoint and address payload structure.
- Creation of the mapping after successful entity creation.
- Storage of the Maconomy job version number.
- Entity-created/address-failed error behavior.
- Final success logging and create API response.
- Engagement update workflow.

## Out of Scope

- Changing the `cch_intergration` package.
- Changing the Part 2 entity-update workflow.
- Implementing address update functionality.
- Supporting multiple customers or multiple customer snapshots for one job.
- Changing the `cw_addresses` column or JSON structure.
- Changing existing CaseWare authentication behavior.
- Automated tests, test scripts, fixtures, mocks, or generated test data.
- Running automated tests.

## Manual Verification Checklist (for later execution by the developer)

No test script will be generated or run. After implementation, manually verify:

1. The Maconomy job-detail request includes all five customer snapshot fields.
2. `/on-create-engagement-post` makes no request to the Maconomy customer-card endpoint.
3. `/sync-todays-created-maconomy-engagements-with-caseware` makes no customer-card request for any candidate job.
4. The CaseWare entity country comes from the job's `country` value for both entry points.
5. The address receives `Name`, `Address1`, `City`, and `Country` from the job snapshot for both entry points.
6. The entity and address are still created in the same order.
7. The mapping continues to store its existing `cw_addresses` entry.
8. `maconomy_customer_number` comes from the job's `customernumber`.
9. `maconomy_customer_version_number` comes from the job's `versionnumber`.
10. `cw_address_id` comes from the CaseWare address-creation response.
11. The entity address-list GET occurs after address POST using page `1` and page size `50`.
12. `caseware_cw_guid` comes from the matching object in the returned address array.
13. A missing matching address or CWGuid is treated as failure and is not saved as a successful mapping state.
14. Mapping list/detail responses continue to contain `cw_addresses`.
15. Duplicate, missing-job, template, entity-failure, and address-failure behavior remains unchanged.
16. The update workflow remains unchanged.

## Implementation Order After Approval

1. Add the customer snapshot fields to the Maconomy job-detail request.
2. Update the create entity country mapping to use the flat job data.
3. Refactor the create router to reuse the flat job detail for entity and address creation.
4. Remove the unused customer-card lookup code.
5. Retrieve and validate the created address CWGuid from the parent entity.
6. Populate the `cw_addresses` entry from the job snapshot and both CaseWare address identifiers.
7. Review all affected references without creating or running tests.
