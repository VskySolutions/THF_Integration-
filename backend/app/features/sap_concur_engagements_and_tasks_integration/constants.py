JOBS_FILTER_FIELDS = [
    "basecurrency",
    "closed",
    "createddate",
    "currency",
    "invoicingprinciple",
    "jobimage",
    "jobname",
    "jobnumber",
    "jobstate",
    "name1",
    "projectmanagername",
    "tasklist",
    "timequantityregistered",
    "totalbillingpriceupdowncurrency",
    "totalopenbillingpricecurrency",
    "totalregbillingpricecurrency",
    "totalregcostpricebase",
]

TASK_FILTER_FIELDS = [
    "taskname",
    "tasklist",
    "description",
    "activitynumber",
    "activitytype",
    "approved",
    "approvaldate",
]

DEFAULT_JOBS_LIMIT = 2000
TASKS_FILTER_LIMIT = 2000

# SAP Concur /list/v4/lists/{id}/bulk validates the ``requests`` array to
# 1-250 entries ("size must be between 1 and 250"); larger payloads are
# rejected with 400 request.validation.error. The service splits anything
# above this limit into sequential chunks.
CONCUR_BULK_MAX_REQUESTS = 250
