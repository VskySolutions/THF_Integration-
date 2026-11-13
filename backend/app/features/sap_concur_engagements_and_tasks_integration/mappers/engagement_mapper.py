"""Shape raw Maconomy jobs/api_tasks records into the engagements payload."""

from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_engagements_payload(
    job_records: list[dict[str, Any]],
    task_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group tasks by tasklist and attach them to their engagement (job).

    Response contract::

        {"engagements": [{"engagement_no", "engagement_name",
                          "customer_name", "tasks": [{"task_no", "task_name"}]}]}

    ``engagement_no`` <- jobs.jobnumber, ``engagement_name`` <- jobs.jobname,
    ``customer_name`` <- jobs.name1, ``task_no`` <- api_tasks.taskname,
    ``task_name`` <- api_tasks.description. Engagements with a blank
    ``tasklist`` or no matching tasks get ``"tasks": []``.
    """
    tasks_by_tasklist: dict[str, list[dict[str, str]]] = {}
    for task in task_records:
        tasklist = _text(task.get("tasklist")).casefold()
        if not tasklist:
            continue
        tasks_by_tasklist.setdefault(tasklist, []).append(
            {
                "task_no": _text(task.get("taskname")),
                "task_name": _text(task.get("description")),
            }
        )

    engagements: list[dict[str, Any]] = []
    for job in job_records:
        tasklist = _text(job.get("tasklist")).casefold()
        engagements.append(
            {
                "engagement_no": _text(job.get("jobnumber")),
                "engagement_name": _text(job.get("jobname")),
                "customer_name": _text(job.get("name1")),
                "tasks": tasks_by_tasklist.get(tasklist, []) if tasklist else [],
            }
        )

    return {"engagements": engagements}
