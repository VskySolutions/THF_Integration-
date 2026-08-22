# Part 2 Plan: Update the CaseWare Cloud Entity

## Objective

Extend the engagement update workflow so that an `UPDATE_REQUIRED` decision updates the mapped entity in CaseWare Cloud.

This part starts only after Part 1 has confirmed all of the following:

- The Maconomy job has an existing mapping.
- The Maconomy job exists and is not a template.
- Both version numbers are valid.
- The current Maconomy `versionnumber` is greater than the last successfully synchronized version stored in the mapping.

Part 2 updates only the CaseWare Cloud entity. Address updates are reserved for Part 3 and are not included here.

## Source Contract

The implementation will follow `backend/PATCH_ENTITY.md`:

1. Authenticate with CaseWare Cloud.
2. GET `/api/v2/entities/{entity_cw_guid}`.
3. Use the existing entity response to build the required PATCH payload.
4. PATCH `/api/v2/entities/{entity_cw_guid}`.

The CaseWare entity GUID will come from `mapping.caseware_cloud_entity_cwid`. It must never be taken from the incoming request.

## Entity Fields in Scope

Based on the documented PATCH payload, Part 2 will send:

| CaseWare field | Value source |
| --- | --- |
| `EntityNo` | Current Maconomy `jobnumber`, matching the creation mapping |
| `Name` | Current Maconomy `jobname`, matching the creation mapping |
| `OwnerType` | Preserve the value returned by the CaseWare GET request |
| `Type` | Preserve the value returned by the CaseWare GET request |

The Maconomy-sourced values updated in this phase are therefore `EntityNo` and `Name`. The CaseWare-required classification values `OwnerType` and `Type` are read first and preserved rather than hard-coded during update.

`OperatingName`, `CountryCode`, and `OrganizationType` are present in the creation payload but are not present in the PATCH contract documented in `PATCH_ENTITY.md`; they will not be added to the PATCH payload in this phase unless the CaseWare API contract is revised before implementation.

## End-to-End Workflow

### When the result is `UP_TO_DATE`

1. Do not call CaseWare Cloud.
2. Leave the mapping version unchanged.
3. Log the successful no-op decision.
4. Return the existing `UP_TO_DATE` response.

### When the result is `STALE_SOURCE_VERSION`

1. Do not call CaseWare Cloud.
2. Leave the mapping version unchanged.
3. Log the decision.
4. Return the existing `STALE_SOURCE_VERSION` response.

### When the result is `UPDATE_REQUIRED`

1. Keep the mapping and fetched Maconomy job details from Part 1.
2. Read `mapping.caseware_cloud_entity_cwid` and reject an empty/invalid mapping value before making a CaseWare request.
3. Authenticate using the existing CaseWare token flow.
4. GET the current entity from `/api/v2/entities/{entity_cw_guid}`.
5. Validate that the response is an object and contains the fields needed for PATCH:
   - `CWGuid`
   - `EntityNo`
   - `Name`
   - `OwnerType`
   - `Type`
6. Confirm that the returned `CWGuid` identifies the mapped entity.
7. Build the PATCH payload with the field mapping defined above.
8. PATCH `/api/v2/entities/{entity_cw_guid}`.
9. Treat only a successful HTTP response as a completed CaseWare update.
10. After PATCH succeeds, update `mapping.maconomy_job_version_number` to the new Maconomy version and commit it.
11. Write a successful `UPDATE` integration log containing:
    - Job number.
    - Previous stored version.
    - Newly stored version.
    - CaseWare entity GUID.
12. Return a response such as:

```json
{
  "jobnumber": "12345",
  "status": "UPDATED",
  "previous_versionnumber": 4,
  "maconomy_versionnumber": 5,
  "caseware_entity_cwid": "entity-guid"
}
```

## State and Failure Rules

### CaseWare GET failure

- Log the `UPDATE` as failed against the mapping.
- Return `502 Bad Gateway` with `Unable to retrieve entity from CaseWare Cloud`.
- Do not PATCH the entity.
- Do not update the mapping version.

### Invalid CaseWare GET response

- Log the `UPDATE` as failed against the mapping.
- Return `502 Bad Gateway` with `Invalid CaseWare Cloud entity response`.
- Do not PATCH the entity.
- Do not update the mapping version.

### CaseWare PATCH failure

- Log the `UPDATE` as failed against the mapping.
- Return `502 Bad Gateway` with `Unable to update entity in CaseWare Cloud`.
- Do not update the mapping version.

### Mapping-version persistence failure after PATCH

- Do not report the workflow as successful.
- Log or propagate the database failure through the application's existing exception handling.
- The stored version remains old, allowing a later retry to detect the job again. A retry may repeat the entity PATCH, so the PATCH payload must remain idempotent for the same Maconomy data.

## Planned Code Changes

### `routers/update_caseware_router.py`

- Retain the Part 1 mapping, template, and version checks.
- Keep the fetched `job_detail`, mapping, and parsed versions available for Part 2.
- For `UP_TO_DATE` and `STALE_SOURCE_VERSION`, preserve the current no-call behavior.
- For `UPDATE_REQUIRED`, call the new CaseWare entity update service.
- Convert CaseWare service failures to logged `502 Bad Gateway` responses.
- Update the stored mapping version only after the CaseWare PATCH succeeds.
- Return `UPDATED` only after both the PATCH and version persistence succeed.

### `mappers/entity_mapper.py`

- Keep `map_maconomy_job_to_caseware_entity(...)` unchanged for the tested creation workflow.
- Add a separate update mapper for the documented PATCH payload.
- Validate required Maconomy values (`jobnumber`, `jobname`).
- Validate and preserve required current CaseWare values (`OwnerType`, `Type`).
- Do not include address fields or undocumented PATCH fields.

### `mappers/__init__.py`

- Export the new entity-update mapper without changing the existing creation mapper export.

### `services/caseware_cloud_service.py`

- Keep `create_entity(...)` and `create_entity_address(...)` unchanged.
- Add an entity-update operation that:
  - Reuses the existing token acquisition method.
  - GETs the current mapped entity.
  - Validates the GET response.
  - Builds the PATCH payload using the update mapper.
  - PATCHes the same mapped entity GUID.
- Reuse one HTTP client and authentication token for the GET and PATCH sequence.
- Raise `CasewareCloudServiceError` with enough context for the router to select the appropriate public error message.

### `services/entity_engagement_mapping_service.py`

- Add a focused method to persist the new `maconomy_job_version_number`.
- Convert the numeric version to the mapping column's current string representation.
- Commit and refresh the mapping only after CaseWare PATCH success.

### Database/schema

- No model or migration change is planned.
- Continue using the existing `maconomy_job_version_number` column.

## Logging Behavior

- `UP_TO_DATE`: one successful update-decision log; no CaseWare call.
- `STALE_SOURCE_VERSION`: one decision log; no CaseWare call.
- `UPDATE_REQUIRED` followed by GET/PATCH failure: one failed update log containing the CaseWare failure context.
- Successful PATCH and mapping-version persistence: one successful update log with the old version, new version, and CaseWare entity GUID.

The workflow should not log `UPDATE_REQUIRED` as the final success before the PATCH completes. Final success means both CaseWare and the mapping version are synchronized.

## Out of Scope

- Creating, updating, or deleting CaseWare entity addresses.
- Comparing `maconomy_customer_version_number` in `cw_addresses`.
- Fetching Maconomy customer details solely for address synchronization.
- Changing the tested creation router, creation mapper, or creation service behavior.
- Polling Maconomy with `changeddate`.
- Database migrations.
- Retry queues or scheduled retries.
- Automated tests, test scripts, fixtures, mocks, or generated test data.
- Running automated tests.

## Manual Verification Checklist (for later execution by the developer)

No test script will be generated or run. After implementation, manually verify:

1. `UP_TO_DATE` makes no CaseWare request and does not change the stored version.
2. `STALE_SOURCE_VERSION` makes no CaseWare request and does not change the stored version.
3. `UPDATE_REQUIRED` uses the CaseWare GUID from the mapping.
4. The GET request occurs before PATCH.
5. The PATCH payload updates `EntityNo` and `Name` from Maconomy and preserves `OwnerType` and `Type` from CaseWare.
6. A CaseWare GET failure returns `502`, logs failure, and leaves the stored version unchanged.
7. An invalid CaseWare GET response returns `502`, logs failure, and does not PATCH.
8. A CaseWare PATCH failure returns `502`, logs failure, and leaves the stored version unchanged.
9. A successful PATCH persists the new Maconomy version and returns `UPDATED`.
10. No address endpoint is called.
11. The create workflow remains unchanged.

## Implementation Order After Approval

1. Add the dedicated entity-update mapper.
2. Add the CaseWare GET-and-PATCH entity service operation.
3. Add the mapping-version persistence method.
4. Connect only the `UPDATE_REQUIRED` branch to the CaseWare update operation.
5. Add final success/failure logging and the `UPDATED` response.
6. Review the implementation without creating or running tests.
