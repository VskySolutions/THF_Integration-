# On-Create Engagement Functional Workflow

This diagram shows the functional workflow for creating one Caseware Cloud
entity and address from a Maconomy job number.

```mermaid
%%{init: {"flowchart": {"curve": "basis"}}}%%
flowchart TD
    A[POST request received with jobnumber] --> B[Validate API key and request body]
    B --> C[Look up mapping by Maconomy job number]
    C --> D{Mapping already exists?}
    D -- Yes --> E[Write linked CREATE failure log]
    E --> F[Return 409 Conflict]
    D -- No --> G[Authenticate with Maconomy and retrieve job]
    G --> H{Maconomy request succeeded?}
    H -- No --> I[Write unlinked CREATE failure log]
    I --> J[Return 502 Bad Gateway]
    H -- Yes --> K{Exactly one job found?}
    K -- No --> L[Write unlinked CREATE failure log: Job not found]
    L --> M[Return 404 Not Found]
    K -- Yes --> N{Job is a template?}
    N -- Yes --> O[Write unlinked CREATE failure log]
    O --> P[Return 400 Bad Request]
    N -- No --> Q{Job has a customer number?}
    Q -- Yes --> R[Retrieve customer details from Maconomy]
    Q -- No --> S[Use empty customer details]
    R --> T{Customer request succeeded?}
    T -- No --> U[Write unlinked CREATE failure log]
    U --> V[Return 502 Bad Gateway]
    T -- Yes --> W[Map job and customer to a Caseware entity]
    S --> W
    W --> X[Authenticate with Caseware Cloud and create entity]
    X --> Y{Entity creation succeeded with CWGuid and Id?}
    Y -- No --> Z[Write unlinked CREATE failure log]
    Z --> AA[Return 502 Bad Gateway]
    Y -- Yes --> AB[Save job-to-entity mapping and job version]
    AB --> AC[Map customer address and create it in Caseware Cloud]
    AC --> AD{Address creation succeeded with numeric Id?}
    AD -- No --> AE[Keep entity and mapping; write linked CREATE failure log]
    AE --> AF[Return 502 partial-failure response]
    AD -- Yes --> AG[Store address metadata on mapping]
    AG --> AH[Write linked CREATE success log]
    AH --> AI[Return Caseware CWGuid and Id]
```

## Functional rules

- The request body must contain a non-empty `jobnumber`, and the router requires
  an accepted API key.
- Duplicate detection uses the entity-engagement mapping table, not the
  integration-log table. A duplicate request is logged against its existing
  mapping and rejected.
- A Maconomy job must resolve to exactly one record and must not have
  `template = true`.
- Customer lookup only runs when the job has a customer number. No customer
  number, or a successful lookup with no matching customer, results in empty
  customer details and does not by itself stop entity creation.
- The Caseware entity mapper requires both `jobnumber` and `jobname`.
- The mapping is committed immediately after entity creation, before address
  creation. Consequently, an address failure leaves the entity and mapping in
  place and makes a retry of this endpoint fail the duplicate check.
- A successful response contains the `CWGuid` and numeric `Id` returned by
  Caseware Cloud.

Endpoint:
`POST /api/v1/caseware-cloud/on-create-engagement-post`
