# Integration service availability controls

Each processing endpoint has one record in the `integration_service` master
table. A request proceeds only when its record exists, has `is_active = true`,
and has `is_deleted = false`.

| Identifier | Endpoint |
| --- | --- |
| `CASEWARE_CREATE_ENGAGEMENT` | `POST /api/v1/caseware-cloud/on-create-engagement-post` |
| `CASEWARE_SYNC_CREATED_ENGAGEMENTS` | `POST /api/v1/caseware-cloud/sync-todays-created-maconomy-engagements-with-caseware` |
| `CASEWARE_UPDATE_ENGAGEMENT` | `POST /api/v1/caseware-cloud/on-update-engagement-post` |
| `CASEWARE_SYNC_UPDATED_ENGAGEMENTS` | `POST /api/v1/caseware-cloud/sync-recently-updated-maconomy-engagements-with-caseware` |

Migration `20260831_0008` creates these records as inactive. There is no
management API. Activate a service through a controlled database change:

```sql
UPDATE integration_service
SET is_active = true,
    updated_on_utc = now()
WHERE identifier_unique_name = 'CASEWARE_CREATE_ENGAGEMENT'
  AND is_deleted = false;
```

Use the same statement with `is_active = false` to disable it. Always set
`updated_on_utc` when making a direct database change.

Inactive services return HTTP 503 with error code
`INTEGRATION_SERVICE_INACTIVE`. Missing and soft-deleted records return HTTP
503 with `INTEGRATION_SERVICE_NOT_CONFIGURED`. Both are handled and persisted
by the shared exception-logging feature, and the endpoint workflow does not
start.
