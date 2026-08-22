# CaseWare Create Integration Gaps and Solutions

## Context

The expected integration is:

```text
One new Maconomy job
    -> one CaseWare Cloud entity
    -> one CaseWare Cloud address
    -> one complete local mapping
```

The CaseWare APIs are external and cannot participate in the same database transaction as the local mapping table. The integration must therefore preserve progress and resume incomplete work safely.

## Items Already Resolved or Accepted

### Duplicate CaseWare entities

Status: Resolved for the current business flow.

- The integration checks the mapping table before creating an entity.
- CaseWare Cloud does not accept two entities with the same `EntityNo`.

### Entity country code

Status: Accepted pending a team decision.

- `CountryCode` remains fixed for now.
- Dynamic mapping from the Maconomy job `country` will be implemented after the team confirms the rule.

## Unresolved Gaps and Solutions

### 1. Mapping exists but address synchronization is incomplete

Implementation status: Resolved through automatic resume in the existing shared create workflow. No separate resume endpoint is used.

Current gap:

- The entity mapping is committed after entity creation and before address synchronization finishes.
- A later create request currently treats any existing mapping as fully synchronized.
- If address creation or address CWGuid retrieval failed, retry is blocked even though the mapping is incomplete.

Solution:

Treat the mapping as a record of synchronization progress, not only as a duplicate check.

```text
Mapping exists with complete address data
    -> already synchronized

Mapping exists with missing/incomplete address data
    -> resume address synchronization
```

A complete `cw_addresses` entry must contain:

- `maconomy_customer_number`
- `cw_address_id`
- `caseware_cw_guid`
- `maconomy_customer_version_number`

Only a complete mapping should produce the existing duplicate/`409 Conflict` response.

### 2. Address POST succeeds but CWGuid lookup fails

Implementation status: Resolved for retry. The integer address ID is persisted before CWGuid lookup, and a later create request resumes lookup without another POST.

Current gap:

- CaseWare address POST returns the integer address ID.
- The integration then retrieves the entity address list to obtain the address CWGuid.
- If that second request fails, the address may already exist in CaseWare, but its ID/CWGuid mapping is incomplete.

Solution:

Persist the returned address ID immediately after the successful POST, before requesting the address list.

Temporary incomplete state:

```json
{
  "maconomy_customer_number": "904844",
  "cw_address_id": "10144",
  "maconomy_customer_version_number": "5"
}
```

Completed state:

```json
{
  "maconomy_customer_number": "904844",
  "cw_address_id": "10144",
  "caseware_cw_guid": "8ce9f107-2543-47ff-a598-61b7a911cb4e",
  "maconomy_customer_version_number": "5"
}
```

When retrying an incomplete mapping that already has `cw_address_id`:

- Do not POST another address.
- Retrieve the CaseWare address list.
- Find the stored address ID.
- Save its CWGuid and complete the mapping.

### 3. Address POST outcome is unknown after a timeout

Implementation status: Resolved for the one-address business rule. An incomplete retry inspects existing CaseWare addresses before deciding whether to POST.

Current gap:

- A network timeout can occur after CaseWare created the address but before the integration received the integer ID.
- Blindly retrying POST could attempt to create another address.

Solution:

Before retrying address POST, retrieve the entity address list.

Because the current business rule is one customer/address per newly created entity:

- If exactly one address exists, adopt that address and save its ID and CWGuid.
- If no address exists, retry address POST.
- If multiple possible addresses exist, do not guess. Log the ambiguity for manual resolution.

If address-field matching is required, compare the job snapshot with:

- `Name`
- `Address1`
- `City`
- `Country`
- `AddressCategory`
- `OwnerCWGuid`

### 4. Address may not be immediately visible after POST

Current gap:

- The address-list GET may occur before CaseWare makes the new address visible.
- The integration could incorrectly report that the created address was not found.

Solution:

- Use a small, bounded retry for the address-list GET.
- Search for the returned address ID after each request.
- If it remains unavailable, keep the saved address ID and mark the mapping as incomplete.
- Allow a later API request or reconciliation process to resume the CWGuid lookup.

The integration must not POST another address when the address ID is already known.

### 5. Address lookup only checks the first 50 records

Current gap:

The current lookup uses:

```text
GET /api/v2/entities/{entity_cw_guid}/addresses?page=1&pageSize=50
```

The address will not be found if it is outside the first page.

Solution:

- Request pages sequentially until the address ID is found.
- Stop when a page contains fewer than `pageSize` records or returns no records.
- Keep a reasonable maximum-page guard to prevent an unbounded external loop.

For a newly created entity with one address, the first page should normally be sufficient, but pagination makes the integration reliable for unexpected external state.

### 6. Error message does not identify the failed stage

Current gap:

The message `Caseware Cloud entity created but address was not created` may be incorrect when address POST succeeded but CWGuid retrieval failed.

Solution:

Use stage-specific integration log and API messages:

- `CaseWare Cloud entity creation failed`
- `CaseWare Cloud address creation failed`
- `CaseWare Cloud address created but CWGuid retrieval failed`
- `CaseWare Cloud address mapping recovery failed`
- `CaseWare Cloud address mapping is ambiguous and requires manual resolution`

This makes operational recovery possible without inspecting raw stack traces.

## Recommended Resumable Workflow

Implementation decision: use the existing shared create workflow for both normal creation and automatic recovery. No separate resume endpoint is required.

### New job with no mapping

1. Fetch the Maconomy job snapshot.
2. Create the CaseWare entity.
3. Save the entity mapping.
4. Create the CaseWare address.
5. Immediately save the returned integer address ID.
6. Retrieve the CaseWare address list.
7. Find the address by ID and save its CWGuid.
8. Mark the workflow successful only when the complete address mapping is stored.

### Existing complete mapping

1. Confirm `cw_addresses` contains both address ID and CWGuid.
2. Return the existing already-synchronized response.
3. Do not create another entity or address.

### Existing mapping with address ID but no CWGuid

1. Do not create another entity.
2. Do not POST another address.
3. Retrieve address-list pages.
4. Find the stored address ID.
5. Save the CWGuid and complete the mapping.

### Existing mapping without an address ID

1. Do not create another entity.
2. Retrieve the CaseWare address list before POSTing.
3. If the entity has exactly one matching address, adopt its ID and CWGuid.
4. If no address exists, create it.
5. If the result is ambiguous, stop and require manual resolution.

## State Persistence Recommendation

The existing JSONB column can represent partial state without a database migration:

- `cw_addresses is null` or empty: entity exists; address state is unknown/incomplete.
- Address entry has `cw_address_id` but no `caseware_cw_guid`: address was created; CWGuid lookup is pending.
- Address entry has both identifiers: create synchronization is complete.

An explicit synchronization-status column could be added later for clearer reporting, but it is not required for the initial recovery solution.

## Implementation Priority

1. Change the existing-mapping check to distinguish complete and incomplete mappings.
2. Separate address POST from address CWGuid lookup so the integer ID can be persisted immediately.
3. Add resume handling for mappings with an address ID but no CWGuid.
4. Add recovery lookup before POST when address creation outcome is unknown.
5. Add bounded retries and pagination to address lookup.
6. Add stage-specific logging and error messages.

## Testing Constraint

Testing remains manual. No automated tests, test scripts, fixtures, mocks, or generated test data should be created or run for this work.
