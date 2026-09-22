# CCH XCM - Task Actual Time Update API

## Endpoint

```
PUT {base_url}/xcmrestservices/vnext/api/v2/Task/{taskId}/actualtime/as
```

## Base URL

```
https://sandboxworkflow.cchaxcess.com
```

## Full URL

```
https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Task/{taskId}/actualtime/as
```

**Note:** `{taskId}` in the URL is the TaskInternalId from Block 2 (stored in Maconomy JobHeader.Text20)

## Headers

| Header | Value | Required |
|--------|-------|----------|
| APIKey | {your-api-key} | Yes |
| Authorization | Bearer {token} | Yes |
| accept | application/json | Yes |
| Content-Type | application/json | Yes |

## Request Body

```json
{
  "userEmail": "string",
  "time": 0
}
```

### Request Fields for Integration (Based on Scope Document)

| Field | Source | Description |
|-------|--------|-------------|
| taskId (URL) | JobHeader.Text20 | CCH Task ID from Block 2 |
| userEmail | Employee.Email | Employee email address |
| time | Calculated | Hours to send (incremental) |

### Hours Calculation (Scope Document)

> Time is sent incrementally for each: EmployeeNumber + JobNumber + TaskName
>
> HoursToSend = Current submitted total - Previously successful CCH total

**Formula:**
```
HoursToSend = CurrentSubmittedMaconomyHours - PreviouslySuccessfulXCMHours
```

**Important:** The previous successful total must come from the existing Maconomy synchronization logic/state, not from a decision made by the local middleware database.

## Success Response (200)

```json
{
  "message": "string"
}
```

## Error Responses

### 400 Bad Request

```json
{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}
```

### 401 Unauthorized

```json
{
  "message": "string"
}
```

## Time Entry Source (Scope Document)

### Maconomy Source
- **Container/module:** Daily Time Registration
- **Entity:** DailyTimesheetLine

### Required Fields from Maconomy

| Field | Description |
|-------|-------------|
| InstanceKey | Unique identifier |
| Linenumber | Line number |
| EmployeeNumber | Employee identifier |
| JobNumber | Job identifier |
| TaskName | Task name |
| NumberOf | Hours worked |
| Submitted | Submission status |
| TheDate | Time entry date |

### Eligibility (Scope Document)

> Only entries with Submitted = true are eligible.

### Time-Entry Prerequisites (Scope Document)

> No employee user is created or updated by this integration. The THF team is responsible for ensuring:
> - Maconomy.Employee.Email = CCH.User.EmailID

## Example cURL

```bash
curl -X 'PUT' \
  'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Task/12345/actualtime/as' \
  -H 'accept: application/json' \
  -H 'APIKey: your-api-key' \
  -H 'Authorization: Bearer your-jwt-token' \
  -H 'Content-Type: application/json' \
  -d '{
  "userEmail": "employee@firm.com",
  "time": 8.5
}'
```

## Notes from Scope Document

1. **Incremental hours only** - Send only the difference (HoursToSend)
2. **Correction window** - Rescan agreed correction window for edited timesheets
3. **Retry with idempotency** - Failed requests are retryable and do not advance the successful Maconomy baseline
4. **Task relationship** - One main XCM TaskInternalId per Maconomy job, multiple tasks represented as roles
5. **Employee email matching** - THF team ensures Maconomy.Employee.Email = CCH.User.EmailID
