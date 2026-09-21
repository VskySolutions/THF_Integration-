# CCH XCM - Task Search API

## Endpoint

```
POST {base_url}/xcmrestservices/vnext/api/v2.1/Task/search
```

## Base URL

```
https://sandboxworkflow.cchaxcess.com
```

## Full URL

```
https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2.1/Task/search
```

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
  "clientName": "string",
  "accountNumber": "string",
  "taskType": "string",
  "taskDescription": "string",
  "fromPeriodEndDate": "MM/DD/YYYY HH:MM:SS",
  "toPeriodEndDate": "MM/DD/YYYY HH:MM:SS",
  "priority": "string",
  "includeStatus": "string",
  "excludeStatus": "string",
  "assignedTo": "string",
  "updatedOnFrom": "MM/DD/YYYY HH:MM:SS",
  "updatedOnTo": "MM/DD/YYYY HH:MM:SS",
  "pageCount": 0,
  "pageIndex": 0
}
```

### Request Fields for Integration (Based on Scope Document)

| Field | Maconomy Source | Description |
|-------|-----------------|-------------|
| accountNumber | CustomerNumber | CCH client account number |
| taskType | **Specification2** | CCH Task Type (not Project.Description) |
| fromPeriodEndDate | Calculated PeriodEndDate | Start of period range |
| toPeriodEndDate | Calculated PeriodEndDate | End of period range |

### Period End Date Calculation (Scope Document)

> The calculated Period End Date is the final day of the customer's fiscal year-end month in the job year.

**Example:**
- Customer FiscalYearEndMonth = December
- Job TheYear = 2026
- PeriodEndDate = 12/31/2026

**Formula:**
```
PeriodEndDate = LastDay(FiscalYearEndMonth, TheYear)
```

## Success Response (200)

```json
{
  "totalCount": 0,
  "results": [
    {
      "externalId": "string",
      "updatedOnDetail": {
        "task": "string",
        "statuslist": "string",
        "checklist": "string",
        "issuepoints": "string",
        "deliverables": "string",
        "assembly": "string",
        "shipping": "string",
        "documentlink": "string",
        "signoff": "string",
        "engagement": "string"
      },
      "taskId": 0,
      "clientName": "string",
      "clientId": 0,
      "statusType": "string",
      "taskTypeCode": "string",
      "taskCategoryCode": "string",
      "taskCategoryName": "string",
      "taskType": "string",
      "periodEndDate": "MM/DD/YYYY HH:MM:SS",
      "priority": "string",
      "taskDescription": "string",
      "originatingLocation": "string",
      "assignedTo": "string",
      "auditPartner": "string",
      "taxPartner": "string",
      "manager": "string",
      "responsiblePerson": "string",
      "taxSenior": "string",
      "auditManager": "string",
      "auditSenior": "string",
      "auditStaff": "string",
      "taxStaff": "string",
      "accountNumber": "string",
      "primaryTaskType": "string"
    }
  ]
}
```

### Response Fields for Integration

| Field | Description |
|-------|-------------|
| totalCount | Number of matching tasks |
| results[].taskId | **TaskInternalId** - Store in Maconomy JobHeader.Text20 |
| results[].accountNumber | CCH account number |
| results[].taskType | Task type |
| results[].periodEndDate | Period end date |
| results[].taskDescription | Task description |

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

## Result Handling

| totalCount | Action |
|------------|--------|
| 0 | No matching task - create new task |
| 1 | Link existing task - use `results[0].taskId` |
| >1 | Send for manual review - do not guess |

## Example cURL

```bash
curl -X 'POST' \
  'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2.1/Task/search' \
  -H 'accept: application/json' \
  -H 'APIKey: your-api-key' \
  -H 'Authorization: Bearer your-jwt-token' \
  -H 'Content-Type: application/json' \
  -d '{
  "accountNumber": "C-100",
  "taskType": "Tax Return",
  "fromPeriodEndDate": "12/31/2026 00:00:00",
  "toPeriodEndDate": "12/31/2026 23:59:59",
  "pageCount": 0,
  "pageIndex": 0
}'
```

## Notes

- API version is `v2.1` (different from auth which uses `v2`)
- Search by accountNumber + taskType + periodEndDate for best matching
- Set both fromPeriodEndDate and toPeriodEndDate to same value for exact match
- taskId in response is equivalent to TaskInternalId in Java reference
- Auth uses `Authorization: Bearer {token}` header (not `securitytoken`)
