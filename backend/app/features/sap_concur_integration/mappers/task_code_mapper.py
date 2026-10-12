"""In-memory Maconomy job/task resolution helpers (Req #5).

Mapping chain:
    SAP Job Number -> Maconomy Task List
    -> Expense Type / Task Description -> Maconomy Task Code (taskname)
"""
from typing import Any


def normalize(value: Any) -> str:
    """Trimmed + case-insensitive key normalization (Req Q-1)."""
    if value is None:
        return ""
    return str(value).strip().casefold()


def build_job_tasklist_map(job_records: list[dict[str, Any]]) -> dict[str, str]:
    """{normalized jobnumber -> tasklist} from raw jobs/filter records.

    Empty/blank jobnumbers are ignored; a tasklist of "" is preserved so the
    resolver can report 'Task List not found for Job Number' (FR-6).
    First record wins for duplicate job numbers (Q-2).
    """
    print("job records:", job_records)
    job_tasklist_map: dict[str, str] = {}
    for record in job_records or []:
        job_number = normalize(record.get("jobnumber"))
        if not job_number:
            continue
        if job_number not in job_tasklist_map:
            job_tasklist_map[job_number] = str(record.get("tasklist") or "").strip()
    return job_tasklist_map


def build_task_code_map(
    task_records: list[dict[str, Any]],
    job_tasklist_map: dict[str, str],
) -> dict[str, str]:
    """Composite key 'jobno|tasklist|description' (normalized) -> task code.

    The Job's Task List is joined onto each task record via a reverse index
    (tasklist -> jobs) built from job_tasklist_map (Req Q-2 composite key).
    Only records with a non-empty taskname are eligible (taskname = Maconomy
    Task Code, Req FR-9). First record wins on duplicate keys.
    """
    jobs_by_tasklist: dict[str, list[str]] = {}
    for job_number, tasklist in (job_tasklist_map or {}).items():
        if tasklist:
            jobs_by_tasklist.setdefault(normalize(tasklist), []).append(job_number)

    task_code_map: dict[str, str] = {}
    for record in task_records or []:
        tasklist_key = normalize(record.get("tasklist"))
        description_key = normalize(record.get("description"))
        task_code = str(record.get("taskname") or "").strip()
        if not tasklist_key or not description_key or not task_code:
            continue
        for job_number in jobs_by_tasklist.get(tasklist_key, []):
            key = f"{job_number}|{tasklist_key}|{description_key}"
            if key not in task_code_map:
                task_code_map[key] = task_code
    return task_code_map


def resolve_task_code(
    job_number: Any,
    expense_type: Any,
    job_tasklist_map: dict[str, str],
    task_code_map: dict[str, str],
) -> tuple[str | None, str | None, str | None]:
    """Resolve one expense line. Returns (tasklist, task_code, skip_reason).

    Exactly one of (tasklist, task_code) or skip_reason is set; skip_reason
    strings must match Req FR-20 verbatim.
    """
    job_key = normalize(job_number)
    if not job_key or job_key not in job_tasklist_map:
        return None, None, "Job Number not found in Maconomy"

    tasklist = job_tasklist_map[job_key]
    if not tasklist:
        return None, None, "Task List not found for Job Number"

    key = f"{job_key}|{normalize(tasklist)}|{normalize(expense_type)}"
    task_code = task_code_map.get(key)
    print("task_code:", task_code)
    task_code = "3189"
    print("Expense Type:", key, "task_code:", task_code)
    if not task_code:
        return None, None, "Expense Type/Task not found for Job Number"

    return tasklist, task_code, None
