# Maconomy to SAP Concur Employee Sync & Version Tracking Architecture

## 1. Overview
This integration synchronizes employee profiles from **Deltek Maconomy** into **SAP Concur (SCIM 2.0)** on a 5-minute recurring interval. It uses an **incremental version comparison engine** backed by a local state tracking table (`employee_sync_tracking`) and an audit trail table (`employee_sync_log`).

---

## 2. Database Schema (Alembic Revision 37: `20261112_0037`)

### A. Current State Ledger: `employee_sync_tracking`
Maintains the current synchronization status and version for each Maconomy employee.

| Column Name | SQL Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, default `gen_random_uuid()` | Unique record ID |
| `maconomy_employee_number` | `VARCHAR(64)` | `NOT NULL`, `UNIQUE`, Indexed | Maconomy unique employee number |
| `sap_concur_user_id` | `VARCHAR(128)` | `NULLABLE`, Indexed | SAP Concur User UUID |
| `maconomy_version` | `VARCHAR(64)` | `NULLABLE` | Last synchronized Maconomy record version (`rowVersion` / `instancekey`) |
| `sync_status` | `VARCHAR(20)` | `NOT NULL`, Indexed, default `'PENDING'` | Values: `SUCCESS`, `FAILED`, `PENDING` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, default `now()` | Record creation timestamp |
| `synced_at` | `TIMESTAMPTZ` | `NULLABLE` | Last successful sync timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, default `now()` | Last state modification timestamp |
| `error_message` | `TEXT` | `NULLABLE` | Latest sync error (preserved for auto-retries) |

### B. Historical Audit & Error Log: `employee_sync_log`
Records every sync attempt, version change, and upstream API response.

| Column Name | SQL Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, default `gen_random_uuid()` | Unique log ID |
| `tracking_id` | `UUID` | `FOREIGN KEY` $\to$ `employee_sync_tracking.id` | Reference to parent tracking row |
| `maconomy_employee_number` | `VARCHAR(64)` | `NOT NULL`, Indexed | Maconomy employee number |
| `sap_concur_user_id` | `VARCHAR(128)` | `NULLABLE` | Concur User UUID |
| `action` | `VARCHAR(32)` | `NOT NULL`, Indexed | `CREATE`, `UPDATE`, `ADOPT_AND_UPDATE`, `SKIP` |
| `status` | `VARCHAR(20)` | `NOT NULL`, Indexed | `SUCCESS` / `FAILED` |
| `old_version` | `VARCHAR(64)` | `NULLABLE` | Version before sync attempt |
| `new_version` | `VARCHAR(64)` | `NULLABLE` | Version achieved or attempted |
| `message` | `TEXT` | `NULLABLE` | Human-readable summary or exception message |
| `details` | `JSONB` | `NULLABLE` | Full Concur SCIM JSON response or error traceback |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Indexed, default `now()` | Execution timestamp |

---

## 3. The 3 Synchronization Scenarios

```
                  Incoming Employee from Maconomy
                                │
                                ▼
               Check Local DB (`employee_sync_tracking`)
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
[ FOUND IN LOCAL DB ]                         [ NOT IN LOCAL DB ]
        │                                               │
Compare Maconomy Version                                │
  vs. Stored DB Version:                                │
        │                                               │
   ├── Same Version:                                    ▼
   │     └─► SKIP (0 API calls)             Search SAP Concur User
   │                                        (POST /profile/identity/v4.1/Users/.search)
   └── Version Changed:                                 │
         ├─► Call SAP Concur UPDATE                     │
         ├─► Update DB: version, synced_at, status      │
         └─► Write to `employee_sync_log`               │
                                       ┌────────────────┴────────────────┐
                                       ▼                                 ▼
                             [ NOT FOUND IN CONCUR ]            [ ALREADY IN CONCUR ]
                                       │                                 │
                               Brand New Employee:              Pre-Existing Employee:
                               ├─ POST /profile/v4/Users        ├─ Adopt Concur User ID
                               ├─ Save to Tracking DB           ├─ PUT /profile/v4/Users/{id}
                               └─ Write to `employee_sync_log`  ├─ Save to Tracking DB
                                                                └─ Write to `employee_sync_log`
```

### Scenario 1: Existing Synced Employee (Found in Local DB)
1. Maconomy returns employee record with current `rowVersion`.
2. Integration checks `employee_sync_tracking.maconomy_version`.
3. **If `stored_version == live_version` AND `sync_status == 'SUCCESS'`:**
   - Skipped immediately without network calls (saves API quota).
4. **If `stored_version != live_version` (or previous run failed):**
   - Calls `PUT /profile/v4/Users/{concur_user_id}`.
   - On success: updates `maconomy_version`, sets `synced_at = now()`, status `SUCCESS`.
   - On failure: **retains old version**, marks `FAILED`, stores error message. The next 5-minute run will automatically retry because the versions still do not match.

### Scenario 2: Brand New Employee (Not in DB, Not in Concur)
1. Employee not found in local DB.
2. Integration queries Concur Identity Search (`POST /profile/identity/v4.1/Users/.search`).
3. Concur returns 0 results.
4. Integration calls `POST /profile/v4/Users` to create the user in Concur.
5. Saves initial tracking record with initial version and `concur_user_id`.

### Scenario 3: Pre-Existing Legacy Employee (In Maconomy & Concur, but NOT in Local DB)
1. Employee not found in local DB.
2. Integration queries Concur Identity Search (`POST /profile/identity/v4.1/Users/.search`).
3. Concur returns existing user (e.g. `5283cef0-6caa-40b5-a977-bbd038d5773e`).
4. **Prevents 409 Conflict error**:
   - Adopts existing Concur User ID.
   - Calls `PUT /profile/v4/Users/{id}` to synchronize latest Maconomy fields.
   - Saves record in `employee_sync_tracking`.
   - Subsequent runs automatically follow **Scenario 1**.

---

## 4. Verified Live Concur SCIM 2.0 API Behaviors

During live endpoint testing against SAP Concur sandbox:
1. **User Search:**
   - Standard GET filter on `/profile/v4/Users` returns HTTP 405.
   - The verified working search endpoint is `POST /profile/identity/v4.1/Users/.search` with schema `urn:ietf:params:scim:api:messages:concur:2.0:SearchRequest`.
2. **User Creation:**
   - Endpoint: `POST /profile/v4/Users`.
   - Enterprise extension requires `companyId` (`f7255b65-38e0-458f-ab3d-40856e011c0b`).
   - `startDate` format must be UTC ISO-8601 with trailing `Z` (e.g., `YYYY-MM-DDTHH:MM:SSZ`).
3. **User Update:**
   - Endpoint: `PUT /profile/v4/Users/{concur_uuid}`.
   - Returns HTTP 200 with the full updated SCIM user entity.

---

## 5. Scheduler Configuration

- **Job Function:** `run_maconomy_concur_employee_sync`
- **Interval:** Every 5 minutes (`minutes=5`)
- **API Target:** `POST /api/v1/sap-concur-employees/sync-cycle`
- **Concurrency Protections:** `max_instances=1`, `coalesce=True`, protected by `_integration_lock` mutex to prevent overlapping sync runs.

