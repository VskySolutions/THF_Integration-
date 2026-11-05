# Maconomy-CaseWare Cloud Integration Scope Document

## 1. Purpose

The purpose of this integration is to automatically synchronize engagement and
client information from Maconomy to CaseWare Cloud.

Maconomy will be the source system. Whenever an eligible engagement is created
or its relevant information is updated in Maconomy, the integration will
create or update the corresponding information in CaseWare Cloud.

The integration service will run automatically every five minutes to identify
and synchronize new or updated engagements.

## 2. Scope Statement

For every eligible engagement in Maconomy, the integration will maintain two
related records in CaseWare Cloud:

1. A CaseWare Cloud Entity record representing the engagement and related
   client information.
2. An Address record associated with the Entity.

When a new engagement is created in Maconomy, the integration will create both
the Entity and Address records in CaseWare Cloud.

When mapped engagement or client information is updated in Maconomy, the
integration will update the corresponding Entity and Address records in
CaseWare Cloud during the next scheduled synchronization.

The integration is one-way:

**Maconomy -> CaseWare Cloud**

Maconomy will remain the source of truth for the synchronized information.
Changes made directly in CaseWare Cloud will not be synchronized back to
Maconomy.

## 3. Engagement Eligibility

A Maconomy engagement will be eligible for synchronization when:

- It is a standard engagement and not an engagement template.
- It is open.
- It was newly created or updated within the integration processing window.
- It contains a valid engagement number.
- It contains a valid engagement name.
- It contains the required client and address information.
- Its country can be mapped to a valid two-character ISO country code.

Closed engagements and engagement templates will not be synchronized.

## 4. Integration Process

The integration service will run every five minutes and perform the following
activities:

1. Retrieve eligible engagements from Maconomy.
2. Retrieve the related engagement, client, and address information.
3. Identify whether each engagement is new or previously synchronized.
4. Search CaseWare Cloud for an existing Entity using the Maconomy engagement
   number.
5. Create or update the CaseWare Entity.
6. Create or update the related Address record.
7. Store the CaseWare identifiers and synchronization version in Maconomy.
8. Record the result of the synchronization.

### 4.1 New Engagement

When a new eligible engagement is identified:

1. The integration retrieves the engagement, client, and address details from
   Maconomy.
2. It searches CaseWare Cloud using the Maconomy engagement number.
3. If an Entity does not exist, it creates a new CaseWare Entity.
4. It creates one Address record under the new Entity.
5. It stores the following synchronization information in the Maconomy
   engagement:
   - CaseWare Entity ID
   - CaseWare Entity number
   - CaseWare Address ID
   - CaseWare Address number
   - Synchronized Maconomy version
   - Last synchronization date and time
6. The engagement is marked as successfully synchronized.

### 4.2 Existing Engagement Update

When a previously synchronized Maconomy engagement is updated:

1. The integration compares the current Maconomy version with the last
   synchronized version.
2. If the Maconomy version has changed, the engagement is selected for
   synchronization.
3. The integration retrieves the mapped CaseWare Entity.
4. It updates the Entity using the latest mapped engagement and client
   information from Maconomy.
5. It retrieves and updates the associated Address.
6. If the Entity does not have an Address, the integration creates one.
7. It updates the synchronization version and timestamp in Maconomy.

The existing CaseWare records will be updated. New duplicate records will not
be created for normal engagement updates.

### 4.3 Existing CaseWare Entity Without a Maconomy Mapping

If an Entity already exists in CaseWare Cloud but its identifiers have not yet
been stored in Maconomy:

1. The integration locates the Entity using the Maconomy engagement number.
2. It links the existing Entity to the Maconomy engagement.
3. It updates the Entity and its Address using the current Maconomy
   information.
4. It stores the CaseWare Entity and Address identifiers in Maconomy.

This prevents the creation of a duplicate CaseWare Entity.

## 5. Field Mapping

### 5.1 Client and Entity Mapping

| Maconomy field | CaseWare Cloud field | Mapping rule |
| --- | --- | --- |
| Engagement number (`jobnumber`) | `EntityNo` | Uses the Maconomy engagement number |
| Engagement name (`jobname`) | `Name` | Uses the Maconomy engagement name |
| Engagement name (`jobname`) | `OperatingName` | Uses the Maconomy engagement name |
| `CustomerRemark27` | `FirstName` | Client's first name |
| `CustomerRemark28` | `MiddleName` | Client's middle name |
| `CustomerRemark29` | `LastName` | Client's last name |
| `CustomerRemark30` | `Suffix` | Client's name suffix |
| Country ISO code | `CountryCode` | Uses a valid two-character ISO country code |
| Fixed value | `OwnerType` | `Client` |
| Fixed value | `Type` | `A` |
| Fixed value | `OrganizationType` | `Corporation` |

The client name fields will be sent to CaseWare Cloud when they are populated
in Maconomy:

- `CustomerRemark27` contains the client's first name.
- `CustomerRemark28` contains the client's middle name.
- `CustomerRemark29` contains the client's last name.
- `CustomerRemark30` contains the client's suffix.

In non-production environments, the CaseWare Entity number may use a `VSKY-`
prefix to prevent test records from conflicting with production records.

### 5.2 Address Mapping

| Maconomy field | CaseWare Cloud field |
| --- | --- |
| `name1` | `Name` |
| `name2` | `Address1` |
| `name3` | `Address2` |
| `name4` | `Address3` |
| `postaldistrict` | `City` |
| `zipcode` | `PostalCode` |
| `telephone` | `PhoneNumber` |
| Country or mapped ISO code | `Country` |
| Country information for US and Canada | `Province` |
| Fixed value | `AddressCategory = Business` |

One Business Address will be maintained for each synchronized Entity.

## 6. Synchronization Identification and Duplicate Prevention

The integration will store a synchronization checkpoint in the Maconomy
engagement's `text19` field.

The checkpoint will contain:

- CaseWare Entity GUID
- CaseWare Entity number
- CaseWare Address GUID
- CaseWare Address number
- Last synchronized Maconomy version
- Last synchronization timestamp in UTC

The synchronization checkpoint will be used to:

- Identify whether the engagement has already been synchronized.
- Determine whether the Maconomy engagement has changed since the last
  synchronization.
- Locate the correct CaseWare Entity and Address.
- Prevent unnecessary updates.
- Prevent duplicate CaseWare records.
- Maintain traceability between Maconomy and CaseWare Cloud.

Before creating a new Entity, the integration will search CaseWare Cloud using
the Maconomy engagement number.

If exactly one matching Entity is found, the integration will update and link
that Entity.

If multiple matching Entities are found, the engagement will not be
synchronized automatically because the correct record cannot be identified
safely.

## 7. In Scope

The following items are included in the integration scope:

- One-way synchronization from Maconomy to CaseWare Cloud.
- Automatic execution of the integration service every five minutes.
- Identification of newly created eligible Maconomy engagements.
- Identification of updated eligible Maconomy engagements.
- Retrieval of related client information from Maconomy.
- Creation of one CaseWare Entity for each Maconomy engagement.
- Creation of one related Address for each CaseWare Entity.
- Updating mapped Entity information after changes in Maconomy.
- Updating mapped client information after changes in Maconomy.
- Updating mapped Address information after changes in Maconomy.
- Creation of an Address when an existing Entity does not have one.
- Country-name and ISO-country-code mapping.
- Searching for an existing Entity before creating a new Entity.
- Prevention of duplicate Entity creation.
- Storage of CaseWare Entity and Address identifiers in Maconomy.
- Storage of the last synchronized Maconomy version.
- Tracking the last successful synchronization date and time.
- Engagement-level and batch-level synchronization logging.
- Handling and logging failed engagement synchronizations.
- Continuing the batch when an individual engagement fails.

## 8. Out of Scope

The following items are outside the integration scope unless separately
approved:

- Synchronization from CaseWare Cloud back to Maconomy.
- Synchronization of changes made directly in CaseWare Cloud back to Maconomy.
- Deletion of CaseWare records when an engagement is deleted in Maconomy.
- Deletion of CaseWare records when an engagement is closed in Maconomy.
- Closure of the Entity after the engagement closes in Maconomy.
- Synchronization of closed engagements.
- Synchronization of engagement templates.
- Creation or maintenance of multiple addresses for one engagement.
- Synchronization of CaseWare engagements, files, workpapers, or documents.
- Synchronization of employees, contacts, teams, permissions, or user access.
- Synchronization of billing information, time entries, expenses, or financial
  transactions.
- Historical bulk migration of all existing Maconomy engagements.
- Automatic conflict resolution when CaseWare information has been changed
  manually.
- Synchronization of fields that are retrieved from Maconomy but are not
  currently mapped, including:
  - Email address
  - Engagement description
  - Engagement start date
  - Work-completed date
