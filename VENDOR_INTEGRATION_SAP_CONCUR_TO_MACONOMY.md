# Vendor Integration — SAP Concur to Maconomy

## Requirement

Vendors are created in SAP Concur and need to be synced to the Vendors (AP module) in Maconomy.

Phases:
- **Part A** — retrieve approved vendors from SAP Concur.
- **Part B** — create each vendor in Maconomy (`vendorcard` container).
- **Part C** — pre-check: only vendors not already present in Maconomy proceed to creation.
- **Part D** — persist a mapping row on successful sync + per-vendor integration logs (DB logging).

## Endpoint

| Item | Value |
|---|---|
| Method / Path | `POST /api/v1/sap-concur-vendors/sync-vendors-sap-maconomy` |
| Request body | none |
| Auth | `X-API-KEY` header + `require_active_integration_service(MACONOMY_SAP_CONCUR_VENDOR_SYNC)` (router-level; both endpoints share it) |
| Success | `{"vendors": [...]}` (HTTP 200) — every Concur vendor: created, skipped-by-pre-check, or failed |
| Failure | HTTP 502 — Concur read failure, Maconomy auth/read failure |

Response items:
- created: `{"vendor_code", "vendor_name", "created": true, "message": "Vendor created successfully"}`
- already exists in Maconomy: `{"vendor_code", "vendor_name", "created": false, "message": "Vendor already exists in Maconomy - skipped"}`
- create failed: `{"vendor_code", "vendor_name", "created": false, "message": "<error>"}`

Order: all skipped first, then all attempted (each group in Concur order).

## Flow

1. **Retrieve SAP Concur vendors** — `SAPConcurVendorService().get_approved_vendors()`:
   - Bearer auth via shared token cache; `GET {base}/api/v3.1/invoice/vendors` with `params={"approved": "true", "limit": 999}` (single call, no pagination).
   - Reads the `Vendor` array and projects each record to: `VendorCode`, `VendorName`, `AddressCode`, `Address1`, `Address2`, `City`, `State`, `PostalCode`, `CountryCode`, `Country`, `CurrencyCode`, `TaxID`, `ContactFirstName`, `ContactLastName`, `ContactEmail`, `ContactPhoneNumber`, `PaymentMethodType`.
2. **Retrieve Maconomy vendors** — `MaconomyService.get_all_vendors()`:
   - `POST {maconomy_url}/maconomy-api/containers/{shortname}/vendorcard/filter`
   - Payload: `{"fields": ["name1", "vendornumber"], "limit": 1000, "offset": N}`
   - Paginated (offset += 1000) until a page returns fewer than 1000 records; page ceiling 100.
   - Returns `[{"vendornumber", "name1"}, ...]`.
3. **Pre-check** — build a set of existing Maconomy `vendornumber` values; keep only Concur vendors whose `VendorCode` is **not** in that set (whitespace-stripped exact match). Already-existing vendors are omitted from the response.
4. **Create loop** (per new vendor, failures do not stop the run):
   - `MaconomyService.get_country_names()` — one `POST {countries}/filter` per run (`{"fields": ["countrycode","countrynumber","eucountrycode","isocode","name"], "limit": 500}`), cached on the service instance; returns `{name.casefold(): name}`. Fetch failure or empty result → `MaconomyServiceError` (vendor fails).
   - `map_concur_vendor_to_maconomy_vendor_card` (mappers/maconomy_vendor_mapper.py) → 11-field payload; `VendorCode`/`VendorName` required; `country` = SAP `State` looked up in that map (case-insensitive), else `united_states_of_america`.
   - Maconomy 3-step create: instance retrieval → card init → card submit (`MaconomyService.create_vendor`).
   - `MaconomyServiceError` for one vendor → `created: false` + message, continue with the next.
5. **DB logging** (Part D) — mapping row + integration log per decision table below.
6. Return `{"vendors": [...]}`.

### DB logging (Part D)

- Mapping row (`sap_concur_vendor_mapping`) inserted **only** when a vendor is created successfully; `sap_concur_vendor_code` is UNIQUE.
- Integration logs (`sap_concur_vendor_integration_logs`) written via `_safe_create_log` (a logging failure never breaks the run, engagements/invoice pattern). All logs use `action=CREATE`.
- Status enum: `SUCCESS` / `FAILED` / `SKIPPED`. Action enum: `CREATE` / `UPDATE` / `RETRY_CREATE`.

| # | Case | Status | sap code | maconomy code | mapping_id | message |
|---|---|---|---|---|---|---|
| 1 | Concur fetch error → 502 | FAILED (single) | NULL | NULL | NULL | `Failed to fetch vendors from SAP Concur: {err}` |
| 2 | Zero vendors from Concur → `{"vendors": []}` (no Maconomy calls) | SKIPPED (single) | NULL | NULL | NULL | `No vendors fetched from concur` |
| 3 | Maconomy auth/pre-check error → 502 | FAILED per vendor | VendorCode | NULL | NULL | `Failed to pre-check existing Maconomy vendors: {err}` |
| 4 | Pre-check hit (already in Maconomy) | SKIPPED per vendor | VendorCode | matched vendornumber | NULL (no mapping row) | `Vendor already exists in Maconomy - skipped` |
| 5 | Created in Maconomy | SUCCESS per vendor | VendorCode | created vendornumber | set (mapping first) | `Vendor created in Maconomy` |
| 6 | Create failed (mapper/Maconomy error) | FAILED per vendor | VendorCode | NULL | NULL | error text |

### Mapping (SAP → Maconomy)

| SAP field | Maconomy field |
|---|---|
| VendorName | `name1` (required) |
| VendorCode | `vendornumber` (required) |
| Address1 | `name2` |
| Address2 | `name3` |
| City | `postaldistrict` |
| PostalCode | `zipcode` |
| State | `country` = SAP `State` resolved case-insensitively against Maconomy `countries.name` via `countries/filter`; no match → `united_states_of_america` |
| — | `currency` = `"USD"` (hardcoded) |
| ContactFirstName + ContactLastName | `attention` = `"First Last"` |
| ContactEmail | `electronicmailaddress` |
| ContactPhoneNumber | `telephone` |

Instance slice (14 fields): `entityname`, `attention`, `country`, `specification4name`, `electronicmailaddress`, `name1`, `name2`, `name3`, `postaldistrict`, `zipcode`, `telephone`, `vendornumber`, `currency`, `paymentmode`.
`paymentmode` is sliced but never written (Concur `PaymentMethodType` mapping dropped per decision).

## Retry API

Single-vendor retry for vendors that failed (or were missed by) the batch sync.

| Item | Value |
|---|---|
| Method / Path | `POST /api/v1/sap-concur-vendors/retry-vendor-sync` |
| Request body | `{"vendor_code": "4029-0"}` (`RetryVendorSyncRequest`, min 1 / max 200 chars) |
| Auth | `X-API-KEY` + `MACONOMY_SAP_CONCUR_VENDOR_SYNC` (router-level, shared with batch endpoint) |
| Success | HTTP 200 — `{"vendor_code", "status": "SUCCESS\|SKIPPED\|FAILED", "message", "result": {...}}` |
| Failures | HTTP 400 blank code · HTTP 404 vendor not in Concur · HTTP 502 Concur/Maconomy connectivity |

Flow (`services/retry_vendor_sync_service.py`):
1. **Concur single fetch** — `SAPConcurVendorService.get_vendor_by_code()`: same `GET /api/v3.1/invoice/vendors` with the `vendorCode` filter enabled (projected to `_VENDOR_FIELDS`); no match → 404 + `FAILED` log.
2. **Maconomy single lookup** — `MaconomyService.get_vendor_by_code()`: ONE `POST {vendorcard}/filter` with `{"restriction": "vendornumber='<code>'", "fields": ["name1","vendornumber"], "limit": 1, "offset": 0}` (SQL-like restriction convention shared with `jobs`/`showvendorinvoices`/`customercard` filters; `'` escaped as `''`). Present → `SKIPPED` (no create, no mapping write).
3. **Conditional create** — only when absent: `create_vendor()` (same 3-step card flow as batch). Mapper/Maconomy rejection → `FAILED` status in the 200 response (logged, no raise).
4. **Mapping upsert** — `vendor_mapping_service.get_by_sap_code()` first; existing row is updated (unique `sap_concur_vendor_code` respected), else inserted.
5. **One log row per attempt** — always `action=RETRY_CREATE` into `sap_concur_vendor_integration_logs` (same table as batch, so it appears in the existing dashboard activity list). Statuses: `SUCCESS` / `SKIPPED` / `FAILED`.

Retry log decision table:

| # | Case | HTTP | status | message |
|---|---|---|---|---|
| 1 | Blank code | 400 | (no log) | `vendor_code is required` |
| 2 | Concur fetch error | 502 | FAILED | `Failed to fetch vendor from SAP Concur: {err}` |
| 3 | Not found in Concur | 404 | FAILED | `Vendor not found in SAP Concur` |
| 4 | Maconomy lookup error | 502 | FAILED | `Failed to pre-check existing Maconomy vendor: {err}` |
| 5 | Already in Maconomy | 200 | SKIPPED | `Vendor already exists in Maconomy - skipped` |
| 6 | Created in Maconomy | 200 | SUCCESS | `Vendor created in Maconomy` |
| 7 | Create rejected | 200 | FAILED | Maconomy error text |
| 8 | Unexpected gap error | re-raise | FAILED | `Retry processing failed: {err}` |

Dashboard: **Retry vendor** button + modal on `sap_concur_vendor_dashboard.html` → `POST /integrations/{id}/retry-sap-concur-vendor` (CSRF form) → server-side call to the API with `X-API-KEY` → `user_activity` `manual_retry` row + flash (mirrors the expense retry button).

## Files

| File | Change |
|---|---|
| `backend/app/features/sap_concur_vendor_integration/routers/sap_concur_vendors.py` | Single sync endpoint: Concur retrieve → Maconomy pre-check → create loop + DB session + safe log/mapping wrappers (6 log cases); `POST /retry-vendor-sync` |
| `backend/app/features/sap_concur_vendor_integration/schemas/sap_concur_vendors.py` | `RetryVendorSyncRequest` DTO |
| `backend/app/features/sap_concur_vendor_integration/services/retry_vendor_sync_service.py` | Retry orchestrator: single Concur fetch → restricted Maconomy lookup → conditional create → mapping upsert → one `RETRY_CREATE` log per attempt |
| `backend/app/features/sap_concur_vendor_integration/services/sap_concur_services.py` | `get_approved_vendors()` (auth block + projection); `get_vendor_by_code()` (single-vendor `vendorCode` filter) |
| `backend/app/features/sap_concur_vendor_integration/services/maconomy_services.py` | Auth (style A) + `create_vendor` 3-step flow + `get_all_vendors()` pre-check read + `get_vendor_by_code()` restricted filter lookup |
| `backend/app/features/sap_concur_vendor_integration/services/integration_log_service.py` | `create_log(...)` — settings-based instance/base_url/username, message `[:1000]` |
| `backend/app/features/sap_concur_vendor_integration/services/vendor_mapping_service.py` | `create_mapping(...)` — commit + refresh; `get_by_sap_code(...)` lookup for retry upsert |
| `backend/app/web/routes.py` | `POST /integrations/{id}/retry-sap-concur-vendor` dashboard handler (CSRF → API → `manual_retry` activity) |
| `backend/app/features/sap_concur_vendor_integration/mappers/maconomy_vendor_mapper.py` | Instance slice payload + card-create field mapping |
| `backend/app/features/sap_concur_vendor_integration/models/vendor_mapping.py` | `SAPConcurVendorMapping` → `sap_concur_vendor_mapping` (UNIQUE sap code) |
| `backend/app/features/sap_concur_vendor_integration/models/integration_log.py` | `SAPConcurVendorIntegrationLog` + status/action enums → `sap_concur_vendor_integration_logs` |
| `backend/alembic/versions/20261116_0044_create_sap_concur_vendor_mapping_and_logs.py` | Creates both tables + 2 enums (`down_revision = 20261112_0043`) — **execute manually** |
| `backend/alembic/env.py` | `# noqa: F401` imports for both new models |
| `backend/app/main.py` | Import + `include_router(..., prefix=settings.api_v1_prefix)` |
| `VENDOR_INTEGRATION_SAP_CONCUR_TO_MACONOMY.md` | This document |

### Tables

`sap_concur_vendor_mapping`: `id` UUID PK · `sap_concur_vendor_code` Text NOT NULL **UNIQUE** · `maconomy_vendor_code` Text nullable · timestamps.

`sap_concur_vendor_integration_logs`: `id` UUID PK · `sap_concur_vendor_mapping_id` FK nullable · `sap_concur_vendor_code` Text **nullable** (NULL for run-level rows) · `maconomy_vendor_code` Text nullable · `instance`/`base_url`/`username` NOT NULL (settings) · `status` ENUM NOT NULL · `action` ENUM NOT NULL · `message` Text nullable · timestamps.

## Known blockers / deviations

- **`country` resolved dynamically (previously blocked):** `"United States"` was rejected live (`invalid enum value: 'United_States'`). Now resolved via `countries/filter` against SAP `State` with `united_states_of_america` fallback (see Mapping).
- **`paymentmodename` → `paymentmode`:** Maconomy rejects `paymentmodename` as an instance field (live-proven 400); slice uses `paymentmode` (still never written).
- Pre-check is exact-string on `vendornumber`; no fuzzy matching (e.g., `E-*` paycor vendors simply never match Concur codes).

## Integration service

| Item | Value |
|---|---|
| Identifier | `MACONOMY_SAP_CONCUR_VENDOR_SYNC` |
| Display name | `SAP Concur to Maconomy vendor sync` |
| Source → target | `SAP Concur - Vendor` → `Maconomy` |
| Registered by | alembic `20261116_0045` (initially **inactive**) |
| Endpoint guard | `require_active_integration_service(...)` alongside `require_api_key` — inactive/not-configured → HTTP 503 |

The dashboard lists the service automatically (DB-driven) with Pause/Enable toggle; toggling affects both manual API calls and the scheduler job.

## Scheduler

| Item | Value |
|---|---|
| Job ID | `sap_concur_vendor_sync` |
| Trigger | interval, `scheduler_sap_concur_vendor_interval_minutes` (default **5**, `ge=1`) |
| Calls | `POST /api/v1/sap-concur-vendors/sync-vendors-sap-maconomy` via shared scheduler client (`X-API-KEY`) |
| Guard rails | `max_instances=1`, `coalesce=True`, `misfire_grace_time=60`, runs under the shared `_integration_lock` |
| Gated by | global `scheduler_enabled` |

Files: `core/config.py` (setting), `schedular_services/constants.py` (path + job ID), `schedular_services/services/sap_concur_vendor_sync.py` (runner), `schedular_services/scheduler.py` (job + `_run_sap_concur_vendor_sync`).

## Monitoring screen

- Route: `GET /integrations/{integration_id}/logs` (existing `integration_logs` route) — new branch for `MACONOMY_SAP_CONCUR_VENDOR_SYNC`.
- Template: `app/templates/sap_concur_vendor_dashboard.html` (modeled on the engagements/tasks screen).
- Shows: Active/Inactive badge, last run, metric cards (Total activity, Success rate, Created, Skipped, Failed), and a per-log table (Time, Vendor code, Maconomy vendor, Action, Status, Result, Details modal with mapping ID/instance/endpoint/username).
- Logs fetched with `selectinload(vendor_mapping)`, latest 1000; run-level rows show `—` for NULL vendor codes. `RETRY_CREATE` rows render with a warning badge.
- **Retry vendor** button (top-right) opens a modal (`vendor_code` input + CSRF) posting to `retry_sap_concur_vendor` — modeled on the expense retry button.

## Out of scope

- No dedupe by name — code-only comparison
- Pre-check is **Maconomy-based only** — the mapping table is never used for pre-check
- Retry API does not re-attempt batch semantics (no bulk retry)

## Migrations (manual)

```
cd backend
alembic upgrade head
```

- `20261116_0044` — creates `sap_concur_vendor_mapping`, `sap_concur_vendor_integration_logs` + both enums (revises `20261112_0043`).
- `20261116_0045` — registers the `MACONOMY_SAP_CONCUR_VENDOR_SYNC` integration-service row (revises `20261116_0044`).

Neither migration is executed by the agent. After migrating, activate the service from the dashboard.

## Verification

1. `python -c "import app.main"` — imports and route registration (endpoint now guarded by the active-service dependency).
2. Both tables present in `Base.metadata`; both migration modules import cleanly; `alembic heads` → `20261116_0045`.
3. Jinja template loads: `templates.env.get_template("sap_concur_vendor_dashboard.html")`.
4. Live run only when explicitly authorized (currently: no live calls).
5. No comments/docstrings in new code (project convention).
