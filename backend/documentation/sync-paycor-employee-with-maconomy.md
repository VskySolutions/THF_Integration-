# Manual Paycor Employee Synchronization Workflow

This endpoint synchronizes one active Paycor employee with Maconomy using the
Paycor employee UUID. It prevents duplicate creation, reconciles existing
Maconomy employees, maintains the employee mapping, and records the result in
the integration log.

Endpoint:
`POST /api/v1/paycor/employees/{paycor_employee_id}/sync-with-maconomy`

```mermaid
flowchart TD
    A[Receive Paycor employee UUID] --> B[Validate API key and active integration]
    B --> C[Retrieve active employee from Paycor]
    C --> D{Employee found?}
    D -- No --> E[Return employee-not-found error]
    D -- Yes --> F[Load mapping and Maconomy employee numbers]
    F --> G{Synchronization state}

    G -- Valid mapping and employee exists --> H[Log and return SKIPPED]
    G -- Mapping exists but employee missing --> I[Log FAILED for reconciliation]
    G -- Employee exists without mapping --> J[Save mapping and return SKIPPED]
    G -- Employee and mapping missing --> K[Prepare Maconomy employee payload]

    K --> L[Omit manager when manager is missing in Maconomy]
    L --> M[Create employee in Maconomy]
    M --> N{Creation succeeded?}
    N -- Yes --> O[Complete mapping and log SUCCESS]
    N -- No --> P[Log FAILED with Maconomy error]
```

## Main rules

- The endpoint requires an API key and an active Paycor integration service.
- The path parameter must be the top-level Paycor employee UUID, not the person
  ID, employee number, manager ID, or onboarding employee ID.
- Only employees returned by the configured Paycor legal entity with
  `statusFilter=Active` can be synchronized.
- Paycor `employeeNumber` is used as Maconomy `employeenumber`.
- The Paycor employee UUID is stored in Maconomy `text10`.
- The mapping table identifies the relationship between the Paycor employee and
  the Maconomy employee.
- A completed mapping is skipped only when the mapped employee number exists in
  Maconomy.
- A mapping that points to a missing Maconomy employee is treated as a failed
  reconciliation case.
- If the employee already exists in Maconomy without a mapping, the mapping is
  created and employee creation is skipped.
- The manager is sent as `superioremployee` only when that manager number exists
  in Maconomy.
- Department, work location, company number, and company name are not currently
  sent because their mappings require client confirmation.
- Maconomy initialized/default values are preserved during employee creation.
- A Maconomy contact person with the same number can block employee creation.
  Such failures are logged and require manual data reconciliation.
- Every created, skipped, or failed operation is written to the integration log.
- A successful response contains the Paycor employee ID, Paycor employee number,
  Maconomy employee number, status, and message.