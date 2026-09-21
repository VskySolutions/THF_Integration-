# Maconomy to CCH/XCM Integration - Logic Flow

## Overview

This document describes the logic flow for integrating Maconomy with CCH/XCM for tax engagement management and time synchronization.

### Integration Goals

1. **Block 1:** Find newly created TAX engagements in Maconomy
2. **Block 2:** Search, create, and link CCH/XCM tasks
3. **Block 3:** Send submitted time entries to CCH/XCM

### Key Principles

- Maconomy is the **authoritative source** for job-task mapping
- Local database is for **error tracking only**, not mapping decisions
- Always **search before create** to avoid duplicates
- Send only **incremental hours** to CCH

---

## Block 1 - Find Syncable TAX Engagements

### Purpose

Poll Maconomy every 5 minutes to discover new TAX jobs that need CCH/XCM processing.

### Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    BLOCK 1 FLOW                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Scheduler  │───▶│   Maconomy  │───▶│   Filter    │     │
│  │  (5 min)    │    │   API Call  │    │   TAX Jobs  │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────┐    ┌─────────────┐       │
│                    │   Read Job  │    │   Check     │       │
│                    │   Fields    │    │   Text20    │       │
│                    └─────────────┘    └─────────────┘       │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────┐    ┌─────────────┐       │
│                    │   Get       │    │   Calculate │       │
│                    │   Customer  │    │   Period    │       │
│                    └─────────────┘    │   End Date  │       │
│                           │           └─────────────┘       │
│                           ▼                  │              │
│                    ┌─────────────┐           │              │
│                    │   Output    │◀──────────┘              │
│                    │   Queue     │                          │
│                    └─────────────┘                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Eligibility Criteria

```python
# Job must satisfy ALL conditions:
is_eligible = (
    job.LocationName == "TAX"           # Case-insensitive
    and job.Closed == False
    and job.Template == False
    and (job.Text20 is None or job.Text20 == "")  # Not yet linked
)
```

### Required Job Fields

| Field | Purpose | Used In |
|-------|---------|---------|
| JobNumber | Unique identifier | Block 2, Block 3 |
| LocationName | TAX filter | Block 1 |
| CustomerNumber | CCH account lookup | Block 2 |
| Specification2 | CCH Task Type | Block 2 |
| TheYear | Period End Date calc | Block 2 |
| Text20 | Existing TaskInternalId | Block 2 |
| Date5 | Existing Period End Date | Block 2 |

### Period End Date Calculation

```python
def calculate_period_end_date(the_year: int, fiscal_year_end_month) -> str:
    """
    Calculate Period End Date as the last day of the customer's
    fiscal year-end month in the job year.
    
    Example:
        TheYear = 2026
        FiscalYearEndMonth = December
        Result = 12/31/2026
    """
    # Handle both numeric (12) and name ("december") formats
    month = convert_month(fiscal_year_end_month)
    last_day = monthrange(the_year, month)[1]
    return f"{month:02d}/{last_day:02d}/{the_year}"
```

### Output

Block 1 outputs a queue of syncable jobs with:

```python
{
    "job_number": "JOB-1234",
    "customer_number": "C-100",
    "specification2": "Tax Return",
    "the_year": 2026,
    "fiscal_year_end_month": "December",
    "period_end_date": "12/31/2026",
    "existing_task_internal_id": None,  # or "12345" if exists
    "existing_period_end_date": None     # or date if exists
}
```

---

## Block 2 - Search, Create, and Link CCH/XCM Task

### Purpose

For each syncable TAX engagement from Block 1:
1. Search CCH for an existing matching task
2. Link it if exactly one match
3. Create a new task if none found
4. Send for manual review if multiple found
5. Write TaskInternalId to Maconomy JobHeader.Text20
6. Write PeriodEndDate to Maconomy JobHeader.Date5

### Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    BLOCK 2 FLOW                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Receive   │───▶│   Validate  │───▶│   Calculate │     │
│  │   Job from  │    │   Customer  │    │   Search    │     │
│  │   Block 1   │    │   Account   │    │   Values    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────┐    ┌─────────────┐       │
│                    │   CCH Auth  │    │   Task      │       │
│                    │   Get Token │    │   Search    │       │
│                    └─────────────┘    └─────────────┘       │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────────────────────────┐      │
│                    │      Check Result Count         │      │
│                    └─────────────────────────────────┘      │
│                           │            │            │       │
│                    ┌──────▼──┐  ┌──────▼──┐  ┌──────▼──┐   │
│                    │ Count=0 │  │ Count=1 │  │ Count>1 │   │
│                    │ Create  │  │  Link   │  │ Manual  │   │
│                    │  Task   │  │  Task   │  │ Review  │   │
│                    └────┬────┘  └────┬────┘  └────┬────┘   │
│                         │           │            │         │
│                         ▼           │            │         │
│                    ┌─────────────┐  │            │         │
│                    │   Task      │  │            │         │
│                    │   Create    │  │            │         │
│                    └────┬────────┘  │            │         │
│                         │           │            │         │
│                         ▼           ▼            ▼         │
│                    ┌─────────────────────────────────┐      │
│                    │   Write to Maconomy             │      │
│                    │   Text20 = TaskInternalId       │      │
│                    │   Date5 = PeriodEndDate         │      │
│                    └─────────────────────────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Step 1: Validate and Calculate

```python
def prepare_task_search(job: dict) -> dict:
    """
    Validate required fields and calculate search values.
    """
    # Validate customer exists in CCH (prerequisite)
    if not job.get("customer_number"):
        raise ValidationError("CustomerNumber is required")
    
    # Calculate Period End Date
    period_end_date = calculate_period_end_date(
        job["the_year"],
        job["fiscal_year_end_month"]
    )
    
    return {
        "account_number": job["customer_number"],      # CCH AccountNumber
        "task_type": job["specification2"],             # CCH TaskType
        "period_end_date": period_end_date,             # CCH PeriodEndDate
        "job_number": job["job_number"],                # For taskDescription
    }
```

### Step 2: Search for Existing Task

```python
async def search_cch_task(search_values: dict, token: str) -> list:
    """
    Call CCH Task Search API.
    
    API: POST /xcmrestservices/vnext/api/v2.1/Task/search
    """
    request_body = {
        "accountNumber": search_values["account_number"],
        "taskType": search_values["task_type"],
        "fromPeriodEndDate": search_values["period_end_date"],
        "toPeriodEndDate": search_values["period_end_date"],
        "pageCount": 0,
        "pageIndex": 0
    }
    
    response = await client.post(
        f"{settings.xcm_base_url}/xcmrestservices/vnext/api/v2.1/Task/search",
        headers={
            "APIKey": settings.xcm_api_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=request_body
    )
    
    return response.json()["results"]
```

### Step 3: Handle Search Results

```python
async def handle_search_results(
    results: list,
    job: dict,
    period_end_date: str,
    token: str
) -> str:
    """
    Handle task search results based on count.
    
    Returns: TaskInternalId to store in Maconomy
    """
    total_count = len(results)
    
    if total_count == 0:
        # No task found - CREATE new task
        task_internal_id = await create_cch_task(job, period_end_date, token)
        return task_internal_id
        
    elif total_count == 1:
        # Exactly one task found - LINK existing
        task_internal_id = results[0]["taskId"]
        return task_internal_id
        
    else:
        # Multiple tasks found - MANUAL REVIEW
        await send_for_manual_review(job, results)
        raise MultipleTasksFoundError(
            f"Found {total_count} matching tasks for job {job['job_number']}"
        )
```

### Step 4: Create New Task (if needed)

```python
async def create_cch_task(
    job: dict,
    period_end_date: str,
    token: str
) -> str:
    """
    Call CCH Task Create API.
    
    API: POST /xcmrestservices/vnext/api/v2/Task
    """
    request_body = {
        "accountNumber": job["customer_number"],
        "taskType": job["specification2"],
        "periodEndDate": f"{period_end_date} 00:00:00",
        "taskDescription": f"{job['job_number']}",
        # Role fields are NOT populated - assigned later during time entry
    }
    
    response = await client.post(
        f"{settings.xcm_base_url}/xcmrestservices/vnext/api/v2/Task",
        headers={
            "APIKey": settings.xcm_api_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=request_body
    )
    
    return response.json()["taskId"]
```

### Step 5: Write Back to Maconomy

```python
async def write_back_to_maconomy(
    job_number: str,
    task_internal_id: str,
    period_end_date: str
) -> None:
    """
    Write TaskInternalId and PeriodEndDate to Maconomy JobHeader.
    
    Fields to update:
    - JobHeader.Text20 = TaskInternalId
    - JobHeader.Date5 = PeriodEndDate
    """
    await maconomy_service.update_job_header(
        job_number=job_number,
        text20=str(task_internal_id),
        date5=period_end_date
    )
```

### Field Mapping Summary

| CCH API Field | Maconomy Source | Description |
|---------------|-----------------|-------------|
| accountNumber | CustomerNumber | CCH client account |
| taskType | Specification2 | CCH Task Type |
| periodEndDate | Calculated | Last day of fiscal year-end month |
| taskDescription | JobNumber | For traceability |
| taskId (response) | - | Store in Text20 |

---

## Block 3 - Send Submitted Time to CCH/XCM

### Purpose

Process submitted Maconomy time entries and send them to CCH/XCM.

### Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    BLOCK 3 FLOW                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Scheduler  │───▶│   Read      │───▶│   Filter    │     │
│  │  (Daily)    │    │   Daily     │    │   Submitted │     │
│  │             │    │   Time Reg  │    │   = True    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────┐    ┌─────────────┐       │
│                    │   Get       │    │   Get       │       │
│                    │   Task      │    │   Employee  │       │
│                    │   Text20    │    │   Email     │       │
│                    └─────────────┘    └─────────────┘       │
│                           │                    │            │
│                           ▼                    ▼            │
│                    ┌─────────────────────────────────┐      │
│                    │   Aggregate Hours by            │      │
│                    │   Employee + Job + Task         │      │
│                    └─────────────────────────────────┘      │
│                           │                                │
│                           ▼                                │
│                    ┌─────────────────────────────────┐      │
│                    │   Calculate Hours to Send       │      │
│                    │   Current - Previously Sent     │      │
│                    └─────────────────────────────────┘      │
│                           │                                │
│                    ┌──────▼──────┐                          │
│                    │ Hours > 0 ? │                          │
│                    └──────┬──────┘                          │
│                     Yes   │   No                            │
│                      │    │    │                            │
│                      ▼    │    ▼                            │
│               ┌──────────┐│  ┌──────────┐                   │
│               │   Send   ││  │   Skip   │                   │
│               │   Time   ││  │          │                   │
│               └────┬─────┘│  └──────────┘                   │
│                    │      │                                 │
│                    ▼      │                                 │
│               ┌──────────┐│                                 │
│               │  Update  ││                                 │
│               │  Sent    ││                                 │
│               │  Hours   ││                                 │
│               └──────────┘│                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Step 1: Read Submitted Time Entries

```python
async def get_submitted_time_entries() -> list:
    """
    Read from Maconomy Daily Time Registration.
    
    Container: DailyTimeRegistration
    Entity: DailyTimesheetLine
    
    Filter: Submitted = True
    """
    return await maconomy_service.get_daily_timesheet_lines(
        filter={"submitted": True}
    )
```

### Step 2: Filter and Validate

```python
def is_eligible_time_entry(entry: dict) -> bool:
    """
    Check if time entry is eligible for CCH submission.
    
    Prerequisites:
    - Submitted = True
    - Employee email exists
    - Job has TaskInternalId (Text20)
    - TaskListLine.TaskText1 = "XCM"
    """
    return (
        entry["submitted"] == True
        and entry.get("employee_email") is not None
        and entry.get("job_text20") is not None
        and entry.get("task_text1") == "XCM"
    )
```

### Step 3: Aggregate Hours

```python
def aggregate_hours(entries: list) -> dict:
    """
    Aggregate hours by EmployeeNumber + JobNumber + TaskName.
    
    Returns: {(emp, job, task): total_hours}
    """
    aggregated = {}
    for entry in entries:
        key = (
            entry["employee_number"],
            entry["job_number"],
            entry["task_name"]
        )
        aggregated[key] = aggregated.get(key, 0) + entry["number_of"]
    return aggregated
```

### Step 4: Calculate Hours to Send

```python
def calculate_hours_to_send(
    current_hours: float,
    previously_sent_hours: float
) -> float:
    """
    Calculate incremental hours to send.
    
    HoursToSend = CurrentSubmittedTotal - PreviouslySuccessfulTotal
    
    Important: Previously sent total must come from Maconomy
    synchronization logic/state, not from local database.
    """
    return current_hours - previously_sent_hours
```

### Step 5: Send to CCH

```python
async def send_time_to_cch(
    task_internal_id: str,
    employee_email: str,
    role: str,
    hours: float,
    token: str
) -> None:
    """
    Call CCH Time Update API.
    
    API: PUT /xcmrestservices/vnext/api/v2/Task/{taskId}/actualtime/as
    """
    await client.put(
        f"{settings.xcm_base_url}/xcmrestservices/vnext/api/v2/Task/"
        f"{task_internal_id}/actualtime/as",
        headers={
            "APIKey": settings.xcm_api_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "userEmail": employee_email,
            "time": hours
        }
    )
```

### Field Mapping Summary

| CCH API Field | Maconomy Source | Description |
|---------------|-----------------|-------------|
| taskId (URL) | JobHeader.Text20 | CCH Task ID |
| userEmail | Employee.Email | Employee email |
| time | Calculated | Hours to send (incremental) |
| role | TaskListLine.Description | Task role (for reference) |

---

## Error Handling Strategy

### API Errors

| Error Type | Action |
|------------|--------|
| 401 Unauthorized | Re-authenticate and retry |
| 400 Bad Request | Log error, send for manual review |
| 404 Not Found | Task doesn't exist, create new |
| 500 Server Error | Retry with exponential backoff |

### Retry Logic

```python
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

async def retry_on_failure(func, *args):
    for attempt in range(MAX_RETRIES):
        try:
            return await func(*args)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # Re-authenticate
                token = await authenticate()
                continue
            elif e.response.status_code >= 500:
                # Server error - retry
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
            raise
```

### Duplicate Prevention

1. **Search before create** - Always check if task exists
2. **Idempotency keys** - Use source + record ID + version
3. **Timeout handling** - If creation times out, search again before retrying

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   COMPLETE DATA FLOW                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MACONOMY                     CCH/XCM                      │
│  ────────                     ────────                      │
│                                                             │
│  ┌─────────────┐              ┌─────────────┐              │
│  │ JobHeader   │              │ Task        │              │
│  │ - JobNumber │──────────────│ - taskId    │              │
│  │ - Text20    │◀─────────────│ - accountNo │              │
│  │ - Date5     │              │ - taskType  │              │
│  └─────────────┘              └─────────────┘              │
│        │                            │                      │
│        ▼                            ▼                      │
│  ┌─────────────┐              ┌─────────────┐              │
│  │ DailyTime   │              │ ActualTime  │              │
│  │ Registration│──────────────│ Update      │              │
│  │ - Submitted │              │ - userEmail │              │
│  │ - NumberOf  │              │ - time      │              │
│  └─────────────┘              └─────────────┘              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Configuration Required

### Environment Variables

```env
# CCH/XCM API Configuration
CCH_AXCESS_URL=https://sandboxworkflow.cchaxcess.com
CCH_AXCESS_CLIENT_ID=your-client-id
CCH_AXCESS_CLIENT_SECRET=your-client-secret

# XCM API Configuration
XCM_API_KEY=your-api-key
XCM_API_VERSION=api/v2
XCM_API_VERSION_TASK_SEARCH=api/v2.1

# Scheduler Configuration
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_MINUTES=5
```

### Settings Structure

```python
class Settings(BaseSettings):
    # Existing
    cch_axcess_url: str
    cch_axcess_client_id: str
    cch_axcess_client_secret: str
    
    # New XCM settings
    xcm_api_key: str
    xcm_api_version: str = "api/v2"
    xcm_api_version_task_search: str = "api/v2.1"
    
    # Computed URLs
    @computed_field
    def xcm_auth_url(self) -> str:
        return f"{self.cch_axcess_url}/xcmrestservices/vnext/api/v2/Authenticate/user"
    
    @computed_field
    def xcm_task_search_url(self) -> str:
        return f"{self.cch_axcess_url}/xcmrestservices/vnext/api/v2.1/Task/search"
    
    @computed_field
    def xcm_task_create_url(self) -> str:
        return f"{self.cch_axcess_url}/xcmrestservices/vnext/api/v2/Task"
    
    @computed_field
    def xcm_time_update_url(self) -> str:
        return f"{self.cch_axcess_url}/xcmrestservices/vnext/api/v2/Task"
```

---

## Testing Strategy

### Unit Tests

| Component | Test Case |
|-----------|-----------|
| Period End Date Calc | Various month formats |
| Task Search | 0, 1, multiple results |
| Task Create | Success, failure, duplicate |
| Hours Calculation | Incremental, zero, negative |
| Time Update | Success, failure |

### Integration Tests

| Flow | Test Case |
|------|-----------|
| Block 1 → Block 2 | Full job discovery and task linking |
| Block 2 → Block 3 | Task creation and time submission |
| Error Recovery | Auth failure, API timeout, retry |

---

## Notes

1. **Maconomy is authoritative** - Never override Text20/Date5 with local data
2. **Search before create** - Prevent duplicate tasks
3. **Incremental hours** - Only send the difference
4. **Correction window** - Rescan for edited timesheets
5. **Manual review** - Multiple task matches require human intervention
