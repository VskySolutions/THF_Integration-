# Maconomy-first mapping and sync checkpoint requirements

## Intended ownership

Maconomy must be the primary source for the CaseWare entity and address mapping
IDs and for the last successfully synchronized source state. The application
mapping table and integration logs remain useful for tracking and diagnostics,
but a missing, stale, or incorrect local row must not decide whether a job is
created, skipped, or updated. Both direct and batch endpoints must use the same
Maconomy-first decision rules.

The repository currently has no CaseWare mapping fields in its Maconomy job
lookup and no write-back operation in the CaseWare feature's Maconomy service.
Before implementation, confirm this contract with the Maconomy owner:

| Required value | Exact Maconomy API field and location to confirm | Why it is needed |
| --- | --- | --- |
| CaseWare entity `CWGuid` (and numeric `Id` if retained) | Job-level field(s) | Identify and verify the CaseWare entity independently of the local database. |
| CaseWare address `CWGuid` and numeric `Id` | Job-level or related address field(s) | Resume creation and target the correct address during update. |
| Last **successfully synced** Maconomy version or equivalent source fingerprint | Separate job-level checkpoint | Decide whether current job data still needs a CaseWare update. This must be distinct from the job's current `versionnumber`. |
| Read and write operations, concurrency token, field editability, permissions, and write response | Maconomy container/API contract | Persist checkpoints safely and verify that they survive rereads. |

If writing mapping fields changes Maconomy's own `versionnumber`, capture the
resulting version after write-back. Otherwise the integration's write can make
the next scheduled run look like an unsynced business update. Confirm how a
customer/address change affects the job's version as well; if it does not,
version-only detection will miss address changes.

## Target decision and recovery rules

1. Read the full current Maconomy job before deciding create versus update.
   Reject missing or template jobs.
2. If Maconomy has no entity mapping, reconcile by the exact CaseWare
   `EntityNo` used at creation (`Vsky-{jobnumber}`) before attempting a new
   entity POST. A single exact match can be adopted; multiple matches require
   manual resolution.
3. After entity creation/reconciliation, write its mapping to Maconomy, then
   synchronize the address. Resume using Maconomy's saved address ID/GUID or a
   uniquely identified CaseWare address; never infer a target from an
   unrelated local row.
4. Advance the Maconomy success checkpoint only after the CaseWare entity and
   address are both confirmed synchronized. On a partial failure, leave it
   behind so a later run retries. Avoid claiming success when the Maconomy
   write-back itself fails.
5. If Maconomy has complete mapping IDs, validate them against CaseWare before
   an update. Compare the current source state with Maconomy's success
   checkpoint. A missing checkpoint requires reconciliation/update even if a
   local version looks equal. Refresh the local row from Maconomy for tracking
   after the authoritative work succeeds.
6. Preserve per-job isolation in batches. The created batch should handle
   unmapped jobs; the changed batch must also handle a job that has no mapping
   but was missed by the created-date window. Both batches must use the shared
   job decision, rather than a local-row prerequisite.

Because Maconomy, CaseWare, and PostgreSQL cannot commit in one transaction,
every write step needs a reread/reconciliation path. In particular, a timeout
after a CaseWare POST or a Maconomy checkpoint write must not produce a second
entity or a false `UP_TO_DATE` decision.

## Acceptance scenarios

| Scenario | Expected authoritative behavior |
| --- | --- |
| New job, no Maconomy IDs or local row | Create/reconcile one CaseWare entity and address, save IDs and success checkpoint in Maconomy, then record local tracking. |
| Maconomy IDs present, local row missing or stale | Use Maconomy IDs; validate against CaseWare, update if needed, and repair local tracking. |
| Local row present, Maconomy IDs missing | Reconcile CaseWare by exact entity number and write the authoritative IDs to Maconomy; do not treat the local row as proof of sync. |
| Maconomy source state newer than its success checkpoint | Update CaseWare entity and address; advance checkpoint only after both succeed. |
| Same Maconomy source state and success checkpoint | Return up to date without relying on the local version. |
| Entity PATCH succeeds, address PATCH fails | Retain old success checkpoint; next run safely retries the incomplete sync. |
| Maconomy write-back fails after CaseWare creation/update | Return failure or pending reconciliation; reread CaseWare on retry and do not create a duplicate. |
| Source job changed but not in created-date window | Updated batch still discovers and synchronizes it. |

The post-change functional documentation should state the actual field names,
write-back ordering, status meanings, retry behavior, and operator resolution
steps after these scenarios are implemented and verified.
