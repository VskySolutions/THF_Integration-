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

## Testing Constraint

Testing is manual. No automated tests, test scripts, fixtures, mocks, or test data will be created or run as part of this work.
