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

    O --> P[Map Maconomy job to Caseware entity payload]
    P --> Q[Authenticate with Caseware Cloud]
    Q --> R[Create Caseware entity]
    R -- Caseware error --> R1[Write CREATE / FAILED integration log]
    R1 --> R2[Raise HTTP 502: Unable to create entity in Caseware Cloud]
    R -- Success --> S[Save CWGuid and job number mapping with cw_addresses NULL]
    S --> T[Map Maconomy customer to Caseware address payload]
    T --> U[Authenticate and create Caseware entity address]
    U -- Address error --> U1[Keep mapping with cw_addresses NULL]
    U1 --> U2[Write linked CREATE / FAILED integration log]
    U2 --> U3[Raise HTTP 502: Entity created but address was not created]
    U -- Success --> V[Save address Id in mapping cw_addresses]
    V --> W[Write linked CREATE / SUCCESS integration log]
    W --> X[Return entity CWGuid and Id]
```

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
| Caseware entity request fails | `CREATE / FAILED` | 502 |
| Entity succeeds but address fails | Linked `CREATE / FAILED` | 502 |
| Entity and address are created | Linked `CREATE / SUCCESS` | 200 |

Unexpected database or application errors are handled by the global exception
handler, written to `exception_logs` when possible, and returned as HTTP 500.
