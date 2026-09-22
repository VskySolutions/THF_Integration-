# CCH XCM - Task Create API

## Endpoint

```
POST {base_url}/xcmrestservices/vnext/api/v2/Task
```

## Base URL

```
https://sandboxworkflow.cchaxcess.com
```

## Full URL

```
https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Task
```

## Headers

| Header | Value | Required |
|--------|-------|----------|
| APIKey | {your-api-key} | Yes |
| Authorization | Bearer {token} | Yes |
| accept | application/json | Yes |
| Content-Type | application/json | Yes |

## Request Body

### Required Fields

```json
{
  "accountNumber": "string",        // Maconomy CustomerNumber
  "taskType": "string",             // From Specification2 (CCH Task Type)
  "periodEndDate": "MM/DD/YYYY HH:MM:SS",  // Calculated period end
  "taskDescription": "string"       // JobNumber + optional JobName
}
```

### Full Schema

```json
{
  "customFields": [
    {
      "optionName": "string",
      "optionValue": "string"
    }
  ],
  "clientName": "string",
  "clientId": 0,
  "accountNumber": "string",
  "taskType": "string",
  "periodEndDate": "MM/DD/YYYY HH:MM:SS",
  "taskDescription": "string",
  "originatingLocation": "string",
  "originatingLocationId": 0,
  "software": "string",
  "projectStart": "string",
  "anticipatedDeliveryDate": "string",
  "priority": "string",
  "difficultyLevel": "string",
  "doRollover": "string",
  "comments": "string",
  "externalId": "string",
  "responsiblePerson": "string",
  "manager": "string",
  "auditManager": "string",
  "auditSenior": "string",
  "auditPartner": "string",
  "auditStaff": "string",
  "taxPartner": "string",
  "taxSenior": "string",
  "taxStaff": "string",
  "role10": "string",
  "role11": "string",
  "role12": "string",
  "role13": "string",
  "role14": "string",
  "role15": "string",
  "role16": "string",
  "role17": "string",
  "role18": "string",
  "role19": "string",
  "role20": "string",
  "role21": "string",
  "role22": "string",
  "role23": "string",
  "role24": "string",
  "role25": "string",
  "role26": "string",
  "role27": "string",
  "role28": "string",
  "role29": "string",
  "role30": "string",
  "role31": "string",
  "role32": "string",
  "role33": "string",
  "role34": "string",
  "role35": "string",
  "role36": "string",
  "role37": "string",
  "role38": "string",
  "role39": "string",
  "role40": "string",
  "role41": "string",
  "role42": "string",
  "role43": "string",
  "role44": "string",
  "role45": "string",
  "role46": "string",
  "role47": "string",
  "role48": "string",
  "role49": "string",
  "role50": "string"
}
```

### Field Mapping for Integration (Based on Scope Document)

| CCH Field | Maconomy Source | Required | Description |
|-----------|-----------------|----------|-------------|
| accountNumber | CustomerNumber | Yes | CCH client account number |
| taskType | **Specification2** | Yes | CCH Task Type |
| periodEndDate | Calculated PeriodEndDate | Yes | Format: MM/DD/YYYY HH:MM:SS |
| taskDescription | JobNumber + JobName | Yes | For traceability |
| clientName | CustomerName | No | Customer name |
| externalId | JobNumber | No | External reference |

### Period End Date Calculation (Scope Document)

> The calculated Period End Date is the final day of the customer's fiscal year-end month in the job year.

**Example:**
- Customer FiscalYearEndMonth = December
- Job TheYear = 2026
- PeriodEndDate = 12/31/2026

### Important Notes from Scope Document

1. **CCH client must already exist** - Client creation is handled by THF team (out of scope)
2. **Task Type mapping** - Use `Specification2` (not Project.Description)
3. **Search before create** - Always search first to avoid duplicates
4. **Task Create API must be confirmed** - Current tenant-specific payload needs verification

## Success Response (200)

```json
{
  "taskId": 0,
  "message": "string"
}
```

### Response Fields

| Field | Description |
|-------|-------------|
| taskId | **TaskInternalId** - Store in Maconomy JobHeader.Text20 |
| message | Status message |

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

## Duplicate Prevention

Before creating a task, always search first using Task Search API.

Use matching key: `accountNumber + taskType + periodEndDate + externalId`

If task creation times out, search again before retrying - CCH may have created the task.

## Example cURL

```bash
curl -X 'POST' \
  'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Task' \
  -H 'accept: application/json' \
  -H 'APIKey: your-api-key' \
  -H 'Authorization: Bearer your-jwt-token' \
  -H 'Content-Type: application/json' \
  -d '{
  "accountNumber": "C-100",
  "taskType": "Tax Return",
  "periodEndDate": "12/31/2026 00:00:00",
  "taskDescription": "JOB-1234 - Smith Tax Return",
  "clientName": "Smith Corporation"
}'
```

## Notes

- API version is `v2` (same as auth endpoint)
- Either clientName or clientId or accountNumber is required
- taskType is mandatory
- periodEndDate format includes time component (MM/DD/YYYY HH:MM:SS)
- taskId in response is equivalent to TaskInternalId in Java reference
- Auth uses `Authorization: Bearer {token}` header
