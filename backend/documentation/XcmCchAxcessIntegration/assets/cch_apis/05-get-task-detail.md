# CCH XCM - Get Task Detail by Task ID API

## Endpoint

```
GET {base_url}/xcmrestservices/vnext/api/v3/Task/{taskId}
```

## Base URL

```
https://sandboxworkflow.cchaxcess.com
```

## Full URL

```
https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v3/Task/{taskId}
```

**Note:** `{taskId}` in the URL is the TaskInternalId stored in Maconomy JobHeader.Text20

## Headers

| Header | Value | Required |
|--------|-------|----------|
| APIKey | {your-api-key} | Yes |
| Authorization | Bearer {token} | Yes |
| accept | application/json | Yes |

## Request Parameters

| Parameter | Location | Type | Required | Description |
|-----------|----------|------|----------|-------------|
| taskId | URL path | integer | Yes | CCH TaskInternalId |

## Success Response (200)

```json
{
  "taskId": 12254560,
  "budgetMethod": "Staffing",
  "clientId": 1655900,
  "clientName": "MONTGOMERY, EARL W., D.D.S.",
  "accountNumber": "20410.T0",
  "primaryTaskType": "Tax - 1040 Individual",
  "groupName": "MONTGOM",
  "groupNumber": "",
  "originatingLocationName": "HQ",
  "taskTypeCode": "40ES",
  "taskType": "INd Estimated Payments",
  "taskCategoryCode": "TX",
  "taskCategoryName": "Tax",
  "periodEndDate": "06/30/2015 00:00:00",
  "difficultyLevel": "Simple",
  "priority": "N",
  "taskDescription": "Estimated Tax Payments",
  "branchName": "HQ",
  "assignedTo": "Rankin, Myles",
  "assignedToUserId": 47515,
  "assignedToEmailId": "test@sandbox.com",
  "currentStatus": "Recurring",
  "statusUpdatedOn": "06/30/2015 02:50:11",
  "completedOn": "",
  "restartDate": "",
  "duedate": "",
  "anticipatedDeliveryDate": "",
  "releaseDate": "",
  "software": "GoSystem RS",
  "infoReceivedOn": "",
  "doRollOver": true,
  "comments": "",
  "externalId": "",
  "customFields": [
    {
      "fieldId": 2,
      "fieldLabel": "Locator Number",
      "fieldValue": "N/A",
      "fieldType": "Text"
    },
    {
      "fieldId": 3,
      "fieldLabel": "Tax Return To Be Signed By",
      "fieldValue": "N/A",
      "fieldType": "Text"
    },
    {
      "fieldId": 4,
      "fieldLabel": "Transmittal Letter To Be Signed By",
      "fieldValue": "N/A",
      "fieldType": "Text"
    },
    {
      "fieldId": 5,
      "fieldLabel": "Caseware Cloud File Name",
      "fieldValue": "\\\\dummycpa013\\Data\\Montgomery, Earl W DDS\\2013\\1213 Earl Montgomery\\dummy",
      "fieldType": "Text"
    }
  ],
  "staffAssignments": [
    {
      "roleId": 1,
      "roleName": "In Charge",
      "assignedTo": "Rankin, Myles  ",
      "assignedToEmail": "test@sandbox.com",
      "assignedToUserId": 47515
    },
    {
      "roleId": 3,
      "roleName": "Engagement SH",
      "assignedTo": "Howell, Winston K.",
      "assignedToEmail": "test@sandbox.com",
      "assignedToUserId": 42764
    },
    {
      "roleId": 5,
      "roleName": "Second Reviewer",
      "assignedTo": "Rankin, Myles  ",
      "assignedToEmail": "test@sandbox.com",
      "assignedToUserId": 47515
    },
    {
      "roleId": 8,
      "roleName": "Preparer",
      "assignedTo": "",
      "assignedToEmail": "",
      "assignedToUserId": 0
    }
  ],
  "returnId": "",
  "lastExtensionFiledOn": "",
  "lastExtensionFiledBy": ""
}
```

## Error Responses

### 401 Unauthorized

```json
{
  "message": "string"
}
```

## Response Fields (Key for Integration)

| Field | Description |
|-------|-------------|
| taskId | CCH TaskInternalId (matches JobHeader.Text20) |
| accountNumber | CCH client account number |
| clientId | CCH internal client ID |
| clientName | CCH client name |
| taskType | Task type |
| taskDescription | Task description |
| periodEndDate | Period end date |
| currentStatus | Current workflow status |
| staffAssignments | List of staff assigned to task roles |

### staffAssignments Fields

| Field | Description |
|-------|-------------|
| roleId | CCH role ID |
| roleName | Role name (e.g., "In Charge", "Preparer") |
| assignedTo | Assigned staff member name |
| assignedToEmail | Assigned staff email |
| assignedToUserId | Assigned staff user ID |

## Example cURL

```bash
curl -X 'GET' \
  'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v3/Task/12254560' \
  -H 'accept: application/json' \
  -H 'APIKey: your-api-key' \
  -H 'Authorization: Bearer your-jwt-token'
```

## Notes

- API version is `v3` (different from auth `v2`, search `v2.1`)
- Use this to retrieve full task details using the TaskInternalId (Text20)
- `staffAssignments` shows the roles and staff assigned to the CCH task
- Role assignment in CCH is aligned separately; the time sync uses the
  employee email from the time entry, not the task's staff assignment
