# Maconomy-CCH/XCM Integration Scope Document

## 1. Purpose

The purpose of this integration is to automatically synchronize newly created
tax engagements from Maconomy to CCH/XCM.

A tax engagement is identified in Maconomy by having `locationname = 2`.

For every eligible tax engagement, the integration will create two related
records in CCH:

1. One CCH Client record.
2. One CCH Task associated with that Client.

The integration service will check Maconomy automatically every five minutes
for newly created eligible tax engagements.

## 2. Scope Statement

Maconomy will be the source system for tax engagement and client information.

When a new eligible tax engagement is created in Maconomy, the integration
will:

1. Retrieve the engagement and related client information.
2. Check whether the engagement already exists as a Client in CCH.
3. Create a new CCH Client when no matching Client exists.
4. Create one Task for the newly created Client.
5. Save the CCH processing result and Task ID in Maconomy.

The integration is one-way:

**Maconomy -> CCH/XCM**

The current integration is creation-only. It does not update existing CCH
Clients or Tasks when information changes in Maconomy.

## 3. Tax Engagement Eligibility

A Maconomy engagement will be eligible for synchronization when:

- It is newly created within the integration's discovery period.
- Its `locationname` value is `2`.
- It is not an engagement template.
- It is open.
- Its `text20` field is empty.
- Its engagement number does not already exist as a CCH Client account number.
- The required employee and engagement information can be resolved.

The primary Maconomy selection conditions are:

| Maconomy field | Required condition |
| --- | --- |
| `locationname` | `2` |
| `template` | `false` |
| `closed` | `false` |
| `text20` | Empty |
| `createddate` | Within the configured new-engagement discovery period |

Before creating the CCH records, the following information must also be
available:

- Billing Manager
- CSE or Engagement Executive
- Engagement Partner
- Return Type
- Client information
- Fiscal year-end month
- Engagement year

### Required role and engagement information

| Business value | Maconomy source | CCH use |
| --- | --- | --- |
| Billing Manager | Employee 6 | `responsiblePerson` |
| CSE or Engagement Executive | Specification 5 employee | `auditPartner` |
| Engagement Partner | Purpose employee | `taxPartner` |
| Return Type | Specification 2 description | Client `primaryTask` and Task `taskType` |

The employee values must resolve to valid employee email addresses.

The Return Type must not be blank and must not be `default`.

If the required role or Return Type information is missing, the engagement will
be marked as ineligible and will not be sent to CCH.

## 4. Integration Process

The integration service will run every five minutes and perform the following
activities:

1. Retrieve newly created tax engagements from Maconomy.
2. Apply the tax-engagement eligibility conditions.
3. Select engagements where `locationname = 2`.
4. Check CCH for an existing Client using the Maconomy engagement number.
5. Exclude engagements that already exist in CCH.
6. Retrieve the related customer, employee, and specification information from
   Maconomy.
7. Validate the required role and Return Type information.
8. Create a CCH Client.
9. Create one CCH Task for the newly created Client.
10. Write the processing results back to Maconomy.
11. Record the integration run result for monitoring and troubleshooting.

### 4.1 New Tax Engagement

When a new eligible tax engagement is identified:

1. The integration retrieves the engagement details from Maconomy.
2. It retrieves the related customer information.
3. It retrieves the related employee email addresses.
4. It retrieves the Specification 1 and Specification 2 descriptions.
5. It calculates the engagement period-end date.
6. It searches CCH using the Maconomy engagement number.
7. If no matching Client exists, it creates a new CCH Client.
8. After the Client is created successfully, it creates one CCH Task.
9. It stores the processing information in Maconomy.

### 4.2 Existing CCH Client

The Maconomy engagement number is mapped to the CCH Client `accountNumber`.

Before creating a new Client, the integration searches CCH for an exact
account-number match.

If a matching CCH Client already exists:

- The engagement is excluded from the creation process.
- A duplicate Client is not created.
- A new Task is not created.
- The existing Client is not updated.
- The existing Task is not updated.

### 4.3 CCH Client Creation

A Client is created only when the Maconomy engagement number does not already
exist in CCH.

The Client may be created as either:

- `Individual`, when the Maconomy Specification 1 description is `individual`.
- `Entity`, for all other Specification 1 descriptions.

### 4.4 CCH Task Creation

A Task is created only after the CCH Client has been created successfully.

One Task will be created for the Client using:

- The Maconomy engagement number as the account number.
- The Return Type as the CCH Task Type.
- The calculated period-end date.
- The Maconomy engagement description as the Task description.

If the engagement description is blank, the engagement number will be used as
the Task description.

## 5. Field Mapping

### 5.1 CCH Client Mapping

| CCH Client field | Maconomy or calculated source | Mapping rule |
| --- | --- | --- |
| `accountNumber` | `jobnumber` | Maconomy engagement number |
| `last_Entity_Name` | `name1` | Used as the Entity name or when individual-name conditions are not satisfied |
| `clientType` | Specification 1 description | `Individual` when the description is `individual`; otherwise `Entity` |
| `responsiblePerson` | Email for `employeenumber6` | Billing Manager |
| `emailId` | `electronicmailaddress` | Client email address |
| `phoneNumber` | `telephone` | Client phone number |
| `originatingLocationName` | Fixed value | `HQ` |
| `active` | Fixed value | `Y` |
| `primaryTask` | Specification 2 description | Return Type |
| `periodEndDate` | Calculated period-end date | Last day of the fiscal year-end month |
| `auditPartner` | Email for `specification5name` | CSE or Engagement Executive |
| `taxPartner` | Email for `purposename` | Engagement Partner |

### 5.2 Individual Client Name Mapping

When Specification 1 identifies the Client as an `Individual`, the following
customer fields are used:

| Maconomy customer field | CCH Client field | Description |
| --- | --- | --- |
| `customerremark27` | `firstName` | Client's first name |
| `customerremark28` | `middleName` | Client's middle name |
| `customerremark29` | `last_Entity_Name` | Client's last name |
| `customerremark30` | `suffix` | Client's name suffix |

The individual-name fields are used when both the first name and last name are
populated.

If either the first name or last name is missing, `name1` is used as the CCH
`last_Entity_Name`.

### 5.3 Employee Role Mapping

| Maconomy role or field | Resolution process | CCH field |
| --- | --- | --- |
| `employeenumber6` | Employee number -> employee email | `responsiblePerson` |
| `specification5name` | Employee number -> employee email | `auditPartner` |
| `purposename` | Employee number -> employee email | `taxPartner` |

### 5.4 Return Type Mapping

| Maconomy source | CCH Client field | CCH Task field |
| --- | --- | --- |
| Specification 2 description | `primaryTask` | `taskType` |

The Specification 2 description represents the tax Return Type.

An engagement will not be synchronized when the resolved Return Type is:

- Blank
- Missing
- `default`

### 5.5 Period-End Date Calculation

The Client's fiscal year-end month is retrieved from the related Maconomy
customer record.

The period-end date is calculated using:

- Maconomy engagement year (`theyear`)
- Customer fiscal year-end month (`fiscalyearendmonth`)
- Last calendar day of that month

For example:

- Engagement year: `2026`
- Fiscal year-end month: `December`
- Calculated period-end date: `12/31/2026`

The calculated value is sent to both the CCH Client and CCH Task.

### 5.6 CCH Task Mapping

| CCH Task field | Maconomy or calculated source | Mapping rule |
| --- | --- | --- |
| `accountNumber` | `jobnumber` | Maconomy engagement number |
| `taskType` | Specification 2 description | Return Type |
| `periodEndDate` | Calculated period-end date | Sent with a time value of `00:00:00` |
| `taskDescription` | `description1` | Uses the engagement description |
| `taskDescription` fallback | `jobnumber` | Used when the engagement description is blank |

## 6. Duplicate Prevention and Maconomy Writeback

### 6.1 Duplicate Prevention

The Maconomy engagement number uniquely identifies the CCH Client.

The mapping is:

**Maconomy `jobnumber` -> CCH `accountNumber`**

Before creating a new Client, the integration searches CCH using the engagement
number. If an exact match is found, the engagement is excluded from the
synchronization process.

This prevents duplicate Client records from being created.

### 6.2 Maconomy Writeback

After CCH processing, the integration writes the result back to the Maconomy
engagement.

| CCH result | Maconomy update |
| --- | --- |
| Client and Task created successfully | Update `date5` and `text20` |
| Client created but Task creation failed | Update `date5` only |
| Client creation failed | Do not update the Maconomy engagement |
| Engagement is ineligible | Do not update the Maconomy engagement |
| Client already exists in CCH | Exclude the engagement from creation processing |

The writeback fields are:

| Maconomy field | Value |
| --- | --- |
| `date5` | Calculated period-end date |
| `text20` | CCH Task ID |

The integration verifies that the Maconomy engagement version has not changed
before saving the result.

After the update, it reads the engagement again and verifies that:

- The Maconomy version increased.
- `date5` was saved correctly.
- `text20` contains the correct CCH Task ID when Task creation succeeded.

## 7. In Scope

The following items are included in the integration scope:

- One-way synchronization from Maconomy to CCH/XCM.
- Automatic checking of Maconomy every five minutes.
- Identification of newly created tax engagements.
- Tax-engagement identification using `locationname = 2 (TAX)`.
- Exclusion of templates and closed engagements.
- Exclusion of engagements already containing a CCH Task ID in `text20`.
- Retrieval of related customer information.
- Retrieval and resolution of employee email addresses.
- Retrieval of Specification 1 and Specification 2 descriptions.
- Calculation of the fiscal period-end date.
- Identification of Individual and Entity Clients.
- Synchronization of individual first name, middle name, last name, and suffix.
- Creation of one CCH Client for each eligible tax engagement.
- Creation of one CCH Task for each newly created Client.
- Search for existing CCH Clients before Client creation.
- Duplicate Client prevention using the engagement number.
- Storage of the calculated period-end date in Maconomy `date5`.
- Storage of the CCH Task ID in Maconomy `text20`.
- Verification of Maconomy writeback.
- Integration-run monitoring and troubleshooting information.
- Isolation of individual engagement failures so other eligible engagements can
  continue.

## 8. Out of Scope

The following items are outside the integration scope unless separately
approved:

- Synchronization from CCH/XCM back to Maconomy.
- Updating an existing CCH Client.
- Updating an existing CCH Task.
- Creating a Task for a Client that already existed before the current
  integration run.
- Synchronizing updated Maconomy engagement information after the CCH Client
  has been created.
- Synchronization of non-tax engagements.
- Synchronization of engagements where `locationname` is not `2 (TAX)`.
- Synchronization of closed engagements.
- Synchronization of engagement templates.
- Deletion or deactivation of CCH Clients.
- Deletion, closure, or reassignment of CCH Tasks.
- Synchronization of time entries, billing, expenses, or financial
  transactions.
- Synchronization of CCH documents, files, or workpapers.
- Synchronization of employees or user accounts as independent CCH records.
- Historical bulk migration of all existing Maconomy engagements.
- Automatic correction of data changed manually in CCH.
- Creation of more than one Client for a Maconomy engagement.
- Creation of more than one Task for a newly created Client.
- Automatic Task recreation when the Client was created but Task creation
  failed.
- Employee time synchronization from Maconomy to CCH is excluded from the
  current scope.
- In Phase 2, Maconomy may send employee time to CCH for selected Tasks
  associated with tax engagements.
