# Part 3 Plan: Update the CaseWare Cloud Entity Address

## Objective

When the existing version logic returns `UPDATE_REQUIRED`, update both the mapped CaseWare entity and its single mapped address using the flat Maconomy job snapshot.

The address mapping now contains:

```json
[
  {
    "maconomy_customer_number": "904844",
    "cw_address_id": "10321",
    "caseware_cw_guid": "address-guid",
    "maconomy_customer_version_number": "5"
  }
]
```

No separate Maconomy customer API will be called.

## CaseWare Address API Contract to Confirm

The repository does not currently document the address PATCH endpoint. Before implementation, confirm whether CaseWare identifies the address by:

- Numeric `cw_address_id`.
- `caseware_cw_guid`.
- Both values.

The likely nested route is:

```text
PATCH /api/v2/entities/{entity_cw_guid}/addresses/{address_identifier}
```

The confirmed CaseWare contract will determine whether `{address_identifier}` is the numeric ID or address CWGuid.

The confirmed address-list route available for lookup is:

```text
GET /api/v2/entities/{entity_cw_guid}/addresses?page=1&pageSize=50
```

## Validation Before CaseWare Updates

For `UPDATE_REQUIRED`, validate before PATCHing the entity:

1. `mapping.cw_addresses` is a list containing exactly one object.
2. `cw_address_id` exists and is a positive integer or numeric string.
3. `caseware_cw_guid` is a non-empty string.
4. `mapping.caseware_cloud_entity_cwid` remains valid.

Invalid mapping state will:

- Produce a failed `UPDATE` integration log.
- Return `500 Internal Server Error`.
- Make no CaseWare entity or address PATCH call.
- Leave all stored versions unchanged.

## Address Field Mapping

| CaseWare field | Source |
| --- | --- |
| `Id` | Mapped `cw_address_id` |
| `CWGuid` | Mapped `caseware_cw_guid`, if required by PATCH |
| `Address1` | Maconomy job `name2` |
| `City` | Maconomy job `postaldistrict` |
| `Country` | Maconomy job `country` |
| `Name` | Maconomy job `name1` |
| `AddressCategory` | `Business`, preserving creation behavior |
| `OwnerCWGuid` | Mapped entity CWGuid |
| `OwnerId` | Entity `Id` returned by the existing CaseWare entity GET |

A separate update mapper will be added so the existing creation mapper continues using `Id: 0`.

## Update Sequence

1. Preserve all existing mapping, Maconomy, template, and version checks.
2. For `UP_TO_DATE` and `STALE_SOURCE_VERSION`, make no entity or address call.
3. For `UPDATE_REQUIRED`, validate the single address mapping first.
4. Authenticate with CaseWare Cloud.
5. GET the mapped entity and validate its `Id` and `CWGuid`.
6. PATCH the entity using the existing entity-update payload.
7. PATCH the mapped address using the confirmed address identifier and flat job snapshot.
8. Only after both PATCHes succeed, update the mapping in one database commit:
   - Set `maconomy_job_version_number` to the new job version.
   - Set `maconomy_customer_number` from job `customernumber`.
   - Set `maconomy_customer_version_number` from job `versionnumber`.
   - Preserve `cw_address_id`.
   - Preserve `caseware_cw_guid`.
9. Log successful synchronization of both entity and address.
10. Return `UPDATED` with the entity CWGuid, address ID, and address CWGuid.

## Failure and Retry Rules

- Entity PATCH failure: do not PATCH the address or update mapping state.
- Address PATCH failure after entity success: do not update mapping state; a later request retries both idempotent PATCHes.
- Database failure after both PATCHes: do not return success; the old version permits a later retry.
- Never advance either stored snapshot version before address PATCH succeeds.
- Never replace the mapped address ID or CWGuid during update.

## Planned Files

### `routers/update_caseware_router.py`

- Extract and validate the single mapped address.
- Pass both address identifiers into the CaseWare update workflow.
- Persist versions only after entity and address success.
- Return and log both address identifiers.

### `mappers/address_mapper.py`

- Keep the creation mapper unchanged.
- Add a dedicated address-update mapper using the job snapshot and mapped identifiers.

### `mappers/__init__.py`

- Export the new update mapper.

### `services/caseware_cloud_service.py`

- Reuse one client, token, and entity GET for the entity/address update sequence.
- Require the entity numeric `Id` for the address owner.
- PATCH the entity, then PATCH the mapped address.
- Raise a distinct error for address PATCH failure.

### `services/entity_engagement_mapping_service.py`

- Add one synchronization-state persistence method.
- Assign a new `cw_addresses` list/object so SQLAlchemy detects the JSONB change.
- Commit job version and customer snapshot metadata together.

### Model, schema, and migration

- No changes required.

## Out of Scope

- Creating an address when mapping data is missing.
- Updating multiple addresses.
- Discovering or replacing a different address during update.
- Changing the create workflow.
- Calling the Maconomy customer-card API.
- Automated tests or test scripts.
- Running automated tests.

## Manual Verification Checklist

1. No address call occurs for `UP_TO_DATE` or `STALE_SOURCE_VERSION`.
2. Missing or malformed address ID/CWGuid fails before entity PATCH.
3. Entity PATCH occurs before address PATCH.
4. Address fields come from the job snapshot.
5. Address failure leaves mapping versions unchanged.
6. Success preserves both address identifiers and updates both snapshot versions.
7. The final response contains address ID and CWGuid.
8. Create endpoints remain unchanged.

## Implementation Order After Approval

1. Confirm the CaseWare address PATCH identifier and payload.
2. Add address mapping validation.
3. Add the address-update mapper.
4. Extend the CaseWare update service.
5. Add atomic mapping-state persistence.
6. Update router logging and response.
7. Review without creating or running tests.
