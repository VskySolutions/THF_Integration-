"""Shape Maconomy engagements payload into a SAP Concur bulk list request."""

from typing import Any


def build_bulk_list_payload(
    engagements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the ``requests`` body for ``POST /list/v4/lists/{id}/bulk``.

    Input is the ``engagements`` list of the Maconomy mapper's output
    (``{"engagements": [...]}``). Output contract::

        {"requests": [{"shortCode", "value"},
                      {"shortCode", "value", "parentCode"}]}

    Mapping: engagement_no -> shortCode, engagement_name -> value;
    task_no -> shortCode, task_name -> value, parent engagement_no ->
    parentCode. All engagements are emitted first so parents always
    precede their tasks. Entries with a blank shortCode are skipped;
    duplicate shortCodes are sent as-is (Concur errors surface in the
    PARTIAL_SUCCESS response). An engagement dict carrying
    ``include_entry=False`` emits only its tasks (parent already synced).
    """
    requests: list[dict[str, str]] = []

    for engagement in engagements:
        engagement_no = str(engagement.get("engagement_no") or "").strip()
        if not engagement_no:
            continue
        if not engagement.get("include_entry", True):
            continue
        requests.append(
            {
                "shortCode": engagement_no,
                "value": str(engagement.get("engagement_name") or ""),
            }
        )

    for engagement in engagements:
        engagement_no = str(engagement.get("engagement_no") or "").strip()
        if not engagement_no:
            continue
        for task in engagement.get("tasks") or []:
            task_no = str(task.get("task_no") or "").strip()
            if not task_no:
                continue
            requests.append(
                {
                    "shortCode": task_no,
                    "value": str(task.get("task_name") or ""),
                    "parentCode": engagement_no,
                }
            )

    return {"requests": requests}
