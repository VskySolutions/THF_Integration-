# Plan: Monthly Journals — reuse existing Maconomy journal per month

**Feature:** `sap_concur_invoice_integration`
**Date:** 2026-11-18
**Status:** PLAN ONLY — NOT STARTED (no code has been written for this)
**Scope note:** No test cases for this feature (user: "No need of the test cases").

---

## 1. Goal

Today every sync run creates **one new journal** (card POST) regardless of
invoice dates. In Maconomy a **journal is monthly**: all invoices whose
InvoiceDate falls within a month must post into **that month's journal**.

New behavior:

- Look up an existing journal covering the invoice's date → **reuse it**
  (append rows to it).
- No journal exists for that month → **create one**; future runs reuse it.
- **One journal per month**; a single sync run may span multiple journals.
- Avoids creating a duplicate journal on every run.

---

## 2. Current architecture

### Unchanged pieces (reused as-is)

- `create_journal_with_invoices()` (`maconomy_invoice_service.py:822`):
  one instance → card POST (journal) → table init → per invoice:
  row POST + interleaved allocation lines (`_create_lines_for_invoice`).
- Reference gates: vendor numbers, entity names (fail-closed, fetched
  once before any write).
- Per-line gates: engagement/task (jobtasks), department.
- `remark5` already-synced pre-check (`get_existing_invoice_ids`).
- FAILED-entry semantics (one failed row/line never aborts the batch).
- Mapping row + integration-log writes (with per-invoice log details).
- Row/line payloads (Q-1 linkage) — see §5 for the journalnumber answer.

### Two reusable patterns already in the codebase

1. **Filter lookup** — `POST {container}/filter` with `restriction` +
   `fields` + `limit`
   (e.g. `_get_maconomy_invoices_by_ids`, line 411; `jobs/filter`;
   `expensesheets/filter`).
2. **Load an existing record into a fresh instance** —
   `POST /instances/{id}/data;{key}={value}` body `{}`
   (allocation: `data;linenumber=..;journalnumber=..`, line 1187;
   expense sheets: `data;expensesheetnumber=..`).
   For `vendorinvoices` the record key is **`journalnumber`**.

---

## 3. Journal-list API (user-provided, 2026-11-18)

```
POST {maconomy_url}/maconomy-api/containers/{shortname}/vendorinvoices/filter
```

- The endpoint is exactly what `_vendor_invoice_url()` already builds
  (`maconomy_invoice_service.py:128`) → reuse it, append `/filter`.
  (`thmasd01` in the user's sample = the `maconomy_shortname` setting.)

**Payload (user's sample):**

```json
{
  "fields": [
    "basecurrency", "companynumber", "createddate",
    "instancekey", "journalnumber", "nameofuser",
    "period", "periodend"
  ],
  "limit": 38
}
```

**Response shape (user's sample):**

```json
{ "panes": { "filter": {
    "records": [
      { "data": { "journalnumber": "...", "period": "...", "periodend": "..." } },
      { "data": { "journalnumber": "...", "period": "...", "periodend": "..." } }
    ] } } }
```

**Implementation notes on the payload:**

- Use `fields` = `["journalnumber", "period", "periodend",
  "companynumber", "instancekey"]` (basecurrency/createddate/nameofuser
  not needed; keep if desired — harmless).
- Use `"limit": 500` (not 38) + truncation tripwire when
  `len(records) == limit` (same pattern as `get_all_vendor_numbers`).
  If `rowCount > limit`, paginate with offset until exhausted.
- Client-side filter: keep only records with
  `companynumber == "100"` (the company used by the journal card
  payload) and non-blank `journalnumber`/`period`/`periodend`.
- Period format: accept both `"YYYY-MM-DD HH:MM:SS"` and `"YYYY-MM-DD"`;
  normalize to `date`. **Confirm with one real sample response before
  implementation.**

---

## 4. Proposed flow

```
run start
 ├─ reference data (vendor/entity) ──────────── unchanged, fail-closed
 ├─ already-synced pre-check (remark5) ──────── unchanged
 ├─ NEW get_journal_periods() ───────────────── ONE /filter call
 │     → [{journalnumber, period, periodend, companynumber}, ...]
 │       (fail-closed: fetch error aborts before any write)
 ├─ group invoice entries by InvoiceDate month (YYYY-MM)
 │     (missing/unparseable InvoiceDate → own group; the row mapper
 │      fails those rows exactly as today)
 └─ for each month group (ordered chronologically):
      ├─ FIND journal where period ≤ InvoiceDate ≤ periodend
      │   ├─ FOUND  → retrieve instance
      │   │           → LOAD existing journal
      │   │             (POST data;journalnumber={jn}, body {})
      │   │           → table init
      │   │           → rows + allocation lines   [NO card POST]
      │   │
      │   └─ MISSING→ retrieve instance
      │               → card init → card POST (static payload, today's
      │                 flow; see Q2 for period/periodend decision)
      │               → extract journalnumber → table init
      │               → rows + allocation lines
      │
      └─ per invoice (unchanged mechanics, group's journalnumber):
           row POST → extract linenumber → allocation lines interleaved
           (row → its lines → next row, WO[#27.8])

cache: month → journalnumber (one lookup/creation per month per run)
```

---

## 5. Answer: does the invoice-row payload need `journalnumber`?

**No — do NOT add `journalnumber` to the invoice-row payload.**

1. **Instance context decides the journal.** Rows POST to
   `.../instances/{id}/data/panes/table`. The instance either
   **created** the journal (card POST) or **loaded** an existing one
   (`data;journalnumber=X`) — the row lands in the right journal
   automatically. This is why it already works today without it.
2. `journalnumber` is not in the vendorinvoices **table slice**
   (slice = vendornumber, entrydate, invoicedate, duedate,
   invoicenumber, entrytext, currency, amountcurrency, vatcurrency,
   financevatcode, purchaseordernumber, documentarchivenumber,
   filename, allocationresponsible, amountexclvatcurrency, remark5) —
   adding it would require a slice change for zero benefit.
3. Where `journalnumber` **is** required (and already handled):
   - **Load URL** for existing journals → `data;journalnumber=X`
     (new code, §6 S4).
   - **Allocation line payload** → already present (Q-1 linkage);
     pass the **group's** journalnumber (existing parameter,
     `maconomy_invoice_service.py:1099`).
   - **DB mapping row** → per-invoice `journalnumber`
     (router fix, §6 R1).

---

## 6. Code changes

### 6.1 Service — `services/maconomy_invoice_service.py`

| # | Change | Detail |
|---|--------|--------|
| S1 | **NEW** `get_journal_periods(client, reconnect_token)` | `POST {_vendor_invoice_url()}/filter` with payload from §3. Parse `panes.filter.records[*].data`; normalize `period`/`periodend` to `date`; filter `companynumber == "100"` + non-blank keys; pagination + truncation tripwire; HTTP error → `MaconomyInvoiceServiceError` (fail-closed, placed with the other reference fetches **before any write**). |
| S2 | **NEW** `_find_journal_for_date(journals, invoice_date)` | Return the journal where `period <= invoice_date <= periodend`, else `None`. Tie-break (Q3 default): exact `period` = month start preferred, else **lowest journalnumber**. |
| S3 | **NEW** `_load_vendor_invoice_data(client, reconnect_token, instance_id, journalnumber)` | `POST .../vendorinvoices/instances/{id}/data;journalnumber={jn}` body `{}` → returns new concurrency token. Mirrors `_load_vendor_invoice_allocation_data` (line 1154). Missing journalnumber or HTTP failure → `MaconomyInvoiceServiceError`. |
| S4 | **REWRITE** `create_journal_with_invoices` | (a) fetch journal periods with the reference data; (b) group entries by `InvoiceDate[:7]`; (c) per group: resolve (S2) → existing = S3 + table init, new = current card flow + table init; (d) existing per-invoice row+lines loop using `group_journalnumber`; (e) `month → journalnumber` cache within the run. Journal-phase errors keep current semantics (raise → router HTTP 500); a **group-level load failure** records that group's invoices as FAILED row entries and continues with the next group. |
| S5 | **Return contract** | Each `invoices[]` entry gains `"journalnumber": str`. Top-level: add `"journals": [{"journalnumber", "period", "periodend", "created": bool}, ...]`; keep `journalnumber` (first group's, for compat) and `journal` (first new-journal card payload or `None`). `lines`/`line_error` unchanged. |
| S6 | **Allocation lines** | `_create_lines_for_invoice(journalnumber=group_journalnumber)` — parameter already exists (line 1099); no logic change. |

### 6.2 Router — `routers/sap_concur_invoices.py`

| # | Change | Detail |
|---|--------|--------|
| R1 | Per-invoice mapping journalnumber | `create_mapping(journalnumber=...)` currently uses ONE run-level `journalnumber_value` (~line 443) → use `invoice_entry.get("journalnumber")` with run-level fallback. |
| R2 | Run-level log message | Reference the `journals` list, e.g. `2 journal(s): 10585 (2026-11, created), 10586 (2026-12, reused)`. |
| R3 | Response | Expose `journals`; `invoice_create` / `lines_created` flag semantics unchanged (true only on full success). |

### 6.3 Mappers — no changes

- Row payload (`map_concur_invoice_to_maconomy_invoice_row`): unchanged
  (no `journalnumber` — see §5).
- Line payload (`map_concur_invoice_line_to_allocation_row`):
  unchanged (`journalnumber` already an argument).

---

## 7. Implementation order

1. S1 — journal-periods fetch (+ fail-closed placement).
2. S2 — date → journal matcher.
3. S3 — load-existing-journal step.
4. S4 — restructure `create_journal_with_invoices` around month groups.
5. S5 + S6 — return contract + line linkage.
6. R1–R3 — router mapping/log/response updates.
7. Verification (§9).

---

## 8. Edge cases

| Case | Handling |
|------|----------|
| InvoiceDate missing/unparseable | Own group; row mapper fails it as today (required-field error) |
| All invoices in one month (common case) | Behavior ≈ today, journal **found** instead of created |
| Run spans 2+ months | 2+ journals processed sequentially; `journallinenumber` still extracted per row from that journal's response |
| Month with no journal (Q2) | **Default (a):** write `period`/`periodend` on the new journal's card payload to force that month — both fields are already in the card slice; exact format to confirm live. Alternatives: (b) accept Maconomy's current-period assignment, (c) fail those invoices. **Q2 not yet confirmed by user.** |
| New journal's period ≠ invoice month | Prevented by Q2(a); if Q2(b), the next run's date lookup would miss it → duplicate-journal risk (documented) |
| Multiple journals cover one date (Q3) | Default: exact `period` = month start, else lowest journalnumber |
| Posted/closed journal (Q4) | User's payload has **no status field** → cannot exclude. Append attempt fails → those invoices FAILED with Maconomy's message (existing per-row handling), batch continues |
| Already-synced invoice | `remark5` pre-check unchanged — never re-posted into any journal |
| Journal-periods reference fetch fails | Abort before any write (fail-closed, same as vendor/entity fetch) |
| `data;journalnumber=X` load fails (404/400) | `MaconomyInvoiceServiceError` → group's invoices recorded FAILED, next group continues |
| Allocation linkage | Lines embed the **group's** journalnumber + the row's linenumber (Q-1, unchanged) |
| Concurrency tokens | Per instance (per group) — tokens never shared across groups |

---

## 9. Verification (no automated test cases, per user)

1. `ruff check app\features\sap_concur_invoice_integration\`
2. Full suite with live-test ignores — **known state: 16 mapper tests
   already failing** from the intentional contract changes
   (entrydate = InvoiceDate, `numberof`, Spec4 disabled, Concur filter
   change). Unrelated to this plan; left as-is per user ("no need of
   the test cases").
3. Manual / live checklist:
   - **Run 1** — month with no journal → journal created,
     `journals[0].created == true`, rows + lines land in it.
   - **Run 2** — same month → **no new journal**; new invoice rows
     appended to the same `journalnumber`; allocation lines carry it.
   - **Mixed-month run** — two journals; each mapping row shows its
     own `journalnumber` (R1).
   - **Re-run** (same invoices) → `remark5` pre-check skips, no
     duplicates.
   - **Gap month** — past month with no journal → per Q2 decision.

---

## 10. Decisions

| # | Decision | Status |
|---|----------|--------|
| Q1 | Journal-list API = `POST {vendorinvoices}/filter` (user-provided payload, §3) | ✅ **Confirmed** |
| — | Invoice-row payload does **NOT** need `journalnumber` (instance context governs) | ✅ **Confirmed (analysis, §5)** |
| Q2 | Month with no journal → force `period`/`periodend` on card **(a)** / accept current period **(b)** / fail invoices **(c)** | ⏳ **Pending — default (a)** |
| Q3 | Multiple journals match → exact month-start `period`, else lowest journalnumber | ⏳ Pending — default accepted unless overridden |
| Q4 | No status field in API → try append; 400 → invoice FAILED, batch continues | ⏳ Pending — default accepted unless overridden |
| Q5 | Invoice month keyed by **InvoiceDate** (required field) | ⏳ Pending — default yes |
| — | No test cases for this feature | ✅ Confirmed (user) |
| — | Previous test-alignment plan (16 failing mapper tests + lint cleanup) dropped for now | ✅ Confirmed (user) |

---

## 11. Out of scope

- Automated test cases for this feature.
- Updating the 16 failing mapper tests / lint cleanup from the earlier
  contract changes (entrydate, `numberof`, Spec4, Concur filter).
- Expense-sheet journals (separate feature/container).
- Changing row/line payloads, gates, dedup, or log structures beyond
  §6.
