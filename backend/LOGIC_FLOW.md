# Create Engagement Logic Flow

This diagram documents the current flow for
`_create_engagement(job_number, session)` used by:

```http
POST /api/v1/caseware-cloud/on-create-engagement-post
```

```mermaid
flowchart TD
    A[Request received] --> B{Valid X-API-KEY?}
    B -- No --> B1[Log exception]
    B1 --> B2[Raise HTTP 401 or 403]
    B -- Yes --> C{Valid body with jobnumber?}
    C -- No --> C1[Log validation exception]
    C1 --> C2[Raise HTTP 422]
    C -- Yes --> D[Look up mapping by job number]

    D --> E{Mapping already exists?}
    E -- Yes --> E1[Write CREATE / FAILED integration log]
    E1 --> E2[Raise HTTP 409: CaseWare Entity record is already created for this Maconomy Job number]
    E -- No --> F[Authenticate with Maconomy]

    F --> G[Fetch job by job number]
    G --> H{Maconomy service error?}
    H -- Yes --> H1[Write CREATE / FAILED integration log]
    H1 --> H2[Raise HTTP 502: Unable to retrieve job details from Maconomy]
    H -- No --> I{Job found?}

    I -- No --> I1[Write CREATE / FAILED integration log]
    I1 --> I2[Raise HTTP 404: Job not found]
    I -- Yes --> J{Job is a template?}

    J -- Yes --> J1[Write CREATE / FAILED integration log]
    J1 --> J2[Raise HTTP 400: Job is a template and cannot be created in Caseware Cloud]
    J -- No --> K{Customer number available?}

    K -- Yes --> L[Authenticate with Maconomy and fetch customer]
    K -- No --> M[Set customer to empty dictionary]
    L --> N{Customer request succeeds?}
    N -- No --> N1[Write CREATE / FAILED integration log]
    N1 --> N2[Raise HTTP 502: Unable to retrieve customer details from Maconomy]
    N -- Yes --> O[Add customer dictionary to job data]
    M --> O

    O --> P[Return Maconomy job and customer dictionary]

    P -. Currently disabled code .-> Q[Map Maconomy job to Caseware entity payload]
    Q -.-> R[Authenticate with Caseware Cloud]
    R -.-> S[Create Caseware entity]
    S -. Caseware error .-> S1[Write CREATE / FAILED integration log]
    S1 -.-> S2[Raise HTTP 502: Unable to create entity in Caseware Cloud]
    S -. Success .-> T[Save CWGuid and job number mapping]
    T -.-> U[Write linked CREATE / SUCCESS integration log]
    U -.-> V[Return CWGuid and Id]
```

## Current behavior

The function currently returns the Maconomy job/customer dictionary after the
template validation. The Caseware entity creation, mapping insert, and success
log block below that return are commented out and therefore do not execute.

## Exception summary

| Condition | Integration log | HTTP status |
|---|---|---:|
| Missing API key | Generic exception log | 401 |
| Invalid API key | Generic exception log | 403 |
| Invalid request body | Generic exception log | 422 |
| Mapping already exists | `CREATE / FAILED` | 409 |
| Maconomy request fails | `CREATE / FAILED` | 502 |
| Job is not found | `CREATE / FAILED` | 404 |
| Job is a template | `CREATE / FAILED` | 400 |
| Caseware request fails | Disabled currently | 502 |
| Caseware entity is created | Disabled currently | 200 |

Unexpected database or application errors are handled by the global exception
handler, written to `exception_logs` when possible, and returned as HTTP 500.
