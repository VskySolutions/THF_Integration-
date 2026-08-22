# Engagement Update Detection Implementation Checklist

- [x] Confirm the approved scope from `PLAN.md` and inspect the existing update flow.
- [x] Refactor the update endpoint to require an engagement mapping before calling Maconomy.
- [x] Preserve Maconomy request and missing-job error handling with update integration logs.
- [x] Reject template engagements with `400 Bad Request` before version comparison.
- [x] Add strict numeric validation for stored and Maconomy version numbers.
- [x] Return `UPDATE_REQUIRED`, `UP_TO_DATE`, or `STALE_SOURCE_VERSION` from the version comparison.
- [x] Log every update decision with the stored and Maconomy version numbers.
- [x] Confirm that detection does not update the stored mapping version or call CaseWare Cloud.
- [x] Review implementation against `PLAN.md` without creating or running tests.

## Router Separation

- [x] Identify update-only code currently located in the create router.
- [x] Move the update endpoint and detection helpers into a dedicated update router file.
- [x] Keep the existing create workflow logic unchanged.
- [x] Export and register the new update router with the application.
- [x] Review router paths and separation without creating or running tests.

## Create Router Rename

- [x] Find all references to the existing create router module.
- [x] Rename `caseware_router.py` to `create_caseware_router.py` without changing its workflow logic.
- [x] Update router exports and application registration to use the create-specific name.
- [x] Review references without creating or running tests.

## Part 2: CaseWare Entity Update

- [x] Review `PATCH_ENTITY.md` and the approved Part 2 plan.
- [x] Add a dedicated PATCH payload mapper without changing the creation mapper.
- [x] Add the CaseWare entity GET-and-PATCH service operation.
- [x] Add post-PATCH mapping-version persistence.
- [x] Connect only `UPDATE_REQUIRED` to the CaseWare update operation.
- [x] Add final update success/failure logging and the `UPDATED` response.
- [x] Confirm address synchronization and create workflow behavior remain unchanged.
- [x] Review Part 2 implementation without creating or running tests.

## Read Router Response Fixes

- [x] Allow integration-log responses to contain a null engagement mapping ID.
- [x] Align mapping response `cw_addresses` with the stored JSON object structure.
- [x] Align the mapping service address annotation with the model and response schema.
- [x] Review the response contracts without creating or running tests.

## Create Flow: Job-Level Customer Snapshot

- [x] Review the approved customer-snapshot plan and shared create workflow.
- [x] Add customer snapshot fields to the Maconomy job-detail request.
- [x] Remove the separate customer-card lookup from the shared create workflow.
- [x] Use flat job data for CaseWare entity and address mapping.
- [x] Keep `cw_addresses` and populate it from job data and the CaseWare address result.
- [x] Remove unused customer-card service methods from `caseware_cloud_intergration` only.
- [x] Confirm both create endpoints use the revised shared workflow.
- [x] Review implementation without creating or running tests.

## Created Address CWGuid Mapping

- [x] Parse the address POST response body as the integer address ID.
- [x] Reuse the authenticated address-creation session to GET the entity address list.
- [x] Request page `1` with page size `50` and parse the returned array.
- [x] Match the created address in that array using the integer ID.
- [x] Validate and return the matching address `CWGuid`.
- [x] Save the address CWGuid as `caseware_cw_guid` in `cw_addresses`.
- [x] Update the create and address-update plans with the new mapping invariant.
- [x] Review implementation without creating or running tests.

## Automatic Incomplete-Create Resume

- [x] Use the shared create workflow for normal creation and recovery.
- [x] Treat only mappings with complete address metadata as already synchronized.
- [x] Persist the integer address ID before attempting CWGuid lookup.
- [x] Resume CWGuid lookup without posting another address when the ID is known.
- [x] Inspect existing CaseWare addresses before POST when the address ID is unknown.
- [x] Adopt the single existing address or create one only when none exists.
- [x] Reject ambiguous multiple-address recovery for manual resolution.
- [x] Keep both existing create endpoints on the same resumable workflow.
- [x] Do not add a separate resume endpoint.
- [x] Review implementation without creating or running tests.

## Testing Constraint

Testing is manual. No automated tests, test scripts, fixtures, mocks, or test data will be created or run as part of this work.
