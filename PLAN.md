# Engagement Update Detection Plan

## Objective

Implement the first part of the Maconomy-to-CaseWare Cloud engagement update flow in `backend/app/features/caseware_cloud_intergration`:

1. Detect a changed Maconomy job.
2. Require an existing row in `caseware_cloud_entity_engagement_mapping`.
3. Fetch the current job details from Maconomy.
4. Compare the Maconomy `versionnumber` with the version stored in the mapping row.
5. Decide whether a CaseWare Cloud update is required.

This phase stops before sending an update to CaseWare Cloud.

## Existing Code That Will Be Reused

- `POST /caseware-cloud/on-update-engagement-post` is the entry point for a single job update, but currently it only fetches and returns Maconomy job/customer details.
- `entity_engagement_mapping_service.get_mapping_by_job_number(...)` already performs the required mapping lookup.
- `MaconomyService.get_job_detail_by_job_number(...)` already fetches a job and includes `versionnumber` in the requested fields.
- The mapping model already stores `maconomy_job_version_number`.
- Existing `IntegrationAction.UPDATE` and integration-log handling will be retained.

## Proposed Flow

### Single-job update request

The existing `POST /caseware-cloud/on-update-engagement-post` endpoint will call one update-detection workflow with the submitted `jobnumber`.

1. Look up the mapping by `maconomy_job_number` **before calling Maconomy**.
2. If no mapping exists:
   - Write a failed `UPDATE` integration log with no mapping ID.
   - Return an HTTP `404 Not Found` error with a clear message such as: `CaseWare Cloud mapping not found for Maconomy job number`.
   - Do not call Maconomy or CaseWare Cloud.
3. If the mapping exists, fetch the full job details from Maconomy using the existing job-detail service.
4. Preserve the current error behavior for Maconomy failures:
   - Maconomy request/response failure: log failure and return `502 Bad Gateway`.
   - Job not found in Maconomy: log failure and return `404 Not Found`.
5. Check the Maconomy `template` field before comparing versions:
   - If `template` is `true`, write a failed `UPDATE` integration log against the existing mapping.
   - Return HTTP `400 Bad Request` with the message: `Engagement is a template and cannot be updated in CaseWare Cloud`.
   - Do not compare versions and do not call CaseWare Cloud.
6. Read both version values:
   - Stored version: `mapping.maconomy_job_version_number`.
   - Current version: `job_detail["versionnumber"]`.
7. Validate and compare the versions numerically, not as strings. For example, version `10` must be greater than version `9`.
8. Return one of these decisions:
   - `UPDATE_REQUIRED` when the Maconomy version is greater than the stored version.
   - `UP_TO_DATE` when the versions are equal.
   - `STALE_SOURCE_VERSION` when the Maconomy version is lower than the stored version; do not update CaseWare Cloud.
9. Log the decision as an `UPDATE` action, including the stored and current version numbers in the message.

The response should contain only useful workflow information, for example:

```json
{
  "jobnumber": "12345",
  "status": "UPDATE_REQUIRED",
  "stored_versionnumber": 4,
  "maconomy_versionnumber": 5
}
```

The fetched job detail should remain available internally for the later CaseWare update phase, but it does not need to be exposed in the detection response.

## Why `changeddate` Filtering Is Not Needed

The update flow already receives the specific `jobnumber` that must be checked. It can fetch that job directly from Maconomy and compare its current `versionnumber` with the last successfully synchronized version stored in the mapping table.

Therefore, this phase will not query Maconomy using `template=false and changeddate>=date(2026,7,1)`. A `changeddate` filter would only be needed for a separate polling or scheduled-discovery flow where job numbers are not already supplied.

## Code Changes Planned

### `routers/update_caseware_router.py`

- Provide the update endpoint and update-detection workflow in a dedicated router module.
- Perform the mapping lookup first and fail immediately when it is absent.
- Fetch Maconomy job details only after the mapping is confirmed.
- Reject template jobs with `400 Bad Request` before version comparison.
- Call a dedicated numeric version-comparison helper.
- Return an explicit detection status.
- Keep CaseWare Cloud update calls out of this phase.

### `routers/create_caseware_router.py`

- Keep the existing, tested create workflow in this router.
- Do not change the create workflow's behavior.

### `services/maconomy_services.py`

- Reuse `get_job_detail_by_job_number(...)` to fetch the supplied job directly.
- Ensure the returned job detail contains `versionnumber`.
- Keep the existing authentication, error conversion, response validation, and result parsing conventions.
- Do not add a changed-job filter or `changeddate` query for this flow.

### `services/entity_engagement_mapping_service.py`

- Reuse `get_mapping_by_job_number(...)` for the initial guard.
- Add no database write for the version during detection.
- A mapping-version update method will be added only with the later successful CaseWare Cloud update phase.

### Schema/model/migrations

- No schema or migration change is expected for this phase because `maconomy_job_version_number` already exists.
- The current database column is text, so conversion and validation will occur before numeric comparison.

## Version Validation Rules

- Both stored and Maconomy version values must be present and convertible to non-negative integers.
- Missing or malformed Maconomy `versionnumber` is treated as an invalid Maconomy response and returned as `502 Bad Gateway` after logging the failure.
- Missing or malformed stored mapping version is treated as invalid integration state. It is logged as a failed update and no CaseWare call is made.
- Versions are never compared lexicographically as strings.

## Important State Rule

Do **not** update `mapping.maconomy_job_version_number` when detection returns `UPDATE_REQUIRED`.

That value will be updated only after the later CaseWare Cloud entity update completes successfully. If it were updated during detection, a CaseWare failure could cause the next run to skip an engagement that is still out of sync.

## Out of Scope for This Phase

- Mapping individual Maconomy fields into a CaseWare Cloud update payload.
- Calling a CaseWare Cloud `PUT`/`PATCH` endpoint.
- Updating CaseWare addresses or comparing customer versions.
- Updating the stored mapping version.
- Retry or rollback behavior for CaseWare Cloud updates.
- Polling or scheduled discovery of changed Maconomy jobs using `changeddate`.
- Creating automated tests, test scripts, fixtures, mocks, or test data.
- Running any automated tests.

## Manual Verification Checklist (for later execution by the developer)

No test script will be generated or run. After implementation, the behavior can be checked manually for these cases:

1. Job number has no mapping: returns `404`, logs failure, and does not call Maconomy.
2. Mapping exists but Maconomy has no job: returns `404` and logs failure against the mapping.
3. Maconomy request fails: returns `502` and logs failure.
4. Mapping exists and Maconomy marks the job as a template: returns `400`, logs failure against the mapping, and does not compare versions or call CaseWare Cloud.
5. Maconomy version is greater: returns `UPDATE_REQUIRED` and leaves the stored version unchanged.
6. Versions are equal: returns `UP_TO_DATE` and makes no CaseWare update call.
7. Maconomy version is lower: returns `STALE_SOURCE_VERSION` and makes no CaseWare update call.
8. Either version is missing or invalid: returns the defined error, logs failure, and makes no CaseWare update call.

## Implementation Order After Plan Approval

1. Add the version parsing/comparison logic.
2. Refactor the update endpoint to enforce mapping-first and template validation behavior.
3. Fetch the supplied job directly from Maconomy and return the detection decision.
4. Review the changes without generating or running tests.
