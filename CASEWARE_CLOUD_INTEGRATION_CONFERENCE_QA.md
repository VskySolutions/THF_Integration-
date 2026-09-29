# Maconomy to CaseWare Cloud Integration - Conference Q&A

## Quick overview

CPA firms use Maconomy to create and manage client jobs. These jobs may be tax or non-tax, and users can make changes to them throughout their lifecycle. CaseWare Cloud is used to manage the documents related to those jobs. When a new job is created in Maconomy, users need a corresponding client entity in CaseWare Cloud where they can organize and maintain the relevant documents.

This integration finds recently created or changed Maconomy jobs and creates or updates the corresponding CaseWare Cloud entity and business address. This gives the client or user the CaseWare record needed for document management without having to create the same record manually. The CaseWare references are then saved back in Maconomy to keep the two records connected.

**Simple message for visitors:** Maconomy is the source of truth for the job and client information. The integration creates or updates the corresponding CaseWare Cloud entity, where the CPA firm's users can manage documents related to that job.

## How it works

1. Find recent Maconomy jobs that are open and are not templates.
2. Check whether each job already has a saved CaseWare Cloud link.
3. For an unlinked job, search CaseWare Cloud using an entity number based on the Maconomy job number.
4. If no entity exists, create the CaseWare entity and one business address.
5. If an entity already exists, update it and save the link instead of creating a duplicate.
6. For a previously linked job, update CaseWare only when Maconomy contains a newer version.
7. Save the CaseWare entity and address references back in Maconomy.
8. Record each result for business and support teams.

> **Key point:** This is not a full two-way synchronization. Maconomy supplies the in-scope business information. CaseWare identifiers are written back only to maintain the connection between the records.

## Questions business and functional visitors may ask

### 1. What business problem does this integration solve?

When a CPA firm creates a new job in Maconomy, whether tax or non-tax, its users may also need a matching entity in CaseWare Cloud to manage the job's documents. Creating that entity manually takes time and can lead to missing, delayed, or duplicate records. The integration creates or links the CaseWare entity automatically so document management can begin sooner.

### 2. What is the main business value?

The main benefits are faster job setup, earlier access to the correct CaseWare entity, fewer duplicate records, more consistent client information, and a reliable place for users to manage job-related documents.

### 3. Which system is the source of truth?

Maconomy is the source of truth for the job, client, and address information covered by the integration. CaseWare Cloud receives that information.

### 4. Is this a two-way synchronization?

No. Business information flows from Maconomy to CaseWare Cloud. The integration writes CaseWare entity and address references back to Maconomy, but it does not use CaseWare changes to update Maconomy business data.

### 5. Which Maconomy jobs are included?

The scheduled process selects jobs that are open, are not templates, and were created or changed today or yesterday. A single job can also be processed manually when needed.

### 6. Why are both today and yesterday checked?

This provides a small safety window for delayed or missed runs. It helps ensure that a recent job is not overlooked because of normal timing differences.

### 7. How are records matched between the systems?

The Maconomy job number is the main business reference. CaseWare uses a corresponding entity number, and the integration also saves the CaseWare entity and address references in Maconomy.

### 8. How does it prevent duplicate CaseWare entities?

Before creating an entity, the integration searches CaseWare using the expected entity number. If one matching entity already exists, it updates and links that entity instead of creating another one.

### 9. What happens if several CaseWare entities have the same number?

The integration does not guess. It reports a failure so the duplicate records can be reviewed and corrected.

### 10. What information is created or updated in the CaseWare entity?

The current flow sends the entity number, job name, operating name, client classification, organization type during creation, and country code. The entity number is based on the Maconomy job number.

### 11. What address information is synchronized?

The current flow supports one business address, including the customer or location name, three address lines, city, country, country code, postal code, and phone number.

### 12. Does the integration synchronize every field from Maconomy?

No. Only the agreed entity and business-address information is included. Other Maconomy fields remain outside the current flow.

The integration also does not upload or synchronize the documents themselves. Users continue to manage those documents within the corresponding CaseWare Cloud entity.

### 13. How does the integration know when an update is needed?

Maconomy keeps a version for each job. The integration compares the current version with the last successfully synchronized version and updates CaseWare only when Maconomy is newer.

### 14. Does every scheduled run overwrite CaseWare?

No. Jobs that have no newer Maconomy version are skipped. When an update is required, only the approved CaseWare entity and address information is refreshed.

### 15. What happens if someone changes an in-scope field directly in CaseWare?

Maconomy remains the source of truth. The next eligible Maconomy update can replace the in-scope CaseWare value. Business ownership of these fields should therefore be clearly agreed.

### 16. What happens if the CaseWare entity exists but has no address?

The integration updates the entity and creates one business address. It then saves both references in Maconomy for future updates.

### 17. What happens if required information is missing?

The job is marked as Failed with a reason. Important information includes the job number, job name, country, and a valid country-code mapping. The data can be corrected and the job retried.

### 18. Will one failed job stop all other jobs?

Normally, no. Each job is processed independently, so one failure is recorded while the remaining jobs continue. A full run may stop if the initial Maconomy or CaseWare connection fails.

### 19. Can one job be retried separately?

Yes. An authorized user can process one Maconomy job by job number. This is useful for correcting data, recovering from a temporary failure, or confirming that a job is already synchronized.

### 20. What results will the business team see?

- **Created:** A new CaseWare entity and business address were created and linked.
- **Updated:** An existing CaseWare entity and address were refreshed from Maconomy.
- **Already synchronized:** CaseWare already has the latest Maconomy version.
- **Failed:** The job needs data correction, system recovery, or manual review.

### 21. Is there an audit trail?

Yes. The integration records one result for each processed job and a summary for the full run. The logs include the job number, action, status, message, version, and saved connection details.

### 22. Can business users view and control the integration?

Yes. The application includes a dashboard for integration status and recent processing history. It also provides a single-job synchronization option for support and recovery.

### 23. Does it run automatically?

It can run automatically at a configurable interval when the scheduler and integration service are enabled. The current application schedule runs the CaseWare process after the CCH/XCM step completes successfully. It can also be started manually.

### 24. What happens if Maconomy or CaseWare Cloud is unavailable?

The run records the failure and can be tried again after service is restored. CaseWare rate-limit responses are also retried a limited number of times before the current job is marked as failed.

### 25. What is not included in the current scope?

The current flow does not upload or synchronize documents. It creates and maintains the CaseWare entity that users rely on for document management. Multiple addresses, contacts, email records, workflow, billing, and other CaseWare modules are also outside the current scope.

### 26. How is access controlled?

Only approved system requests can start the integration. The integration service must be enabled, and access to Maconomy and CaseWare Cloud depends on configured accounts and permissions.

### 27. What must the customer confirm before go-live?

The customer should confirm job-number rules, country mappings, entity and address field ownership, CaseWare client settings, run frequency, system permissions, and who will review failures. Existing duplicate entities should be resolved before the first production run.

### 28. Who should own the process after go-live?

A business or support owner should monitor results, correct missing or conflicting information, resolve duplicate entities, and retry failed jobs. Clear ownership prevents exceptions from remaining unresolved.

### 29. Can the scope be expanded later?

Yes. Additional CaseWare records, fields, addresses, contacts, workflow steps, or other processes can be considered after the business rules and ownership are agreed.

### 30. What type of organization benefits most from this integration?

It is most useful for CPA firms that create and manage tax and non-tax jobs in Maconomy and use CaseWare Cloud to organize the related client documents, especially where teams currently create CaseWare entities by hand.

## Closing statement

The Maconomy to CaseWare Cloud integration gives CPA firms a controlled and traceable way to create or update the CaseWare entity needed for each eligible job. Its value is straightforward: less manual setup, fewer duplicate records, consistent client information, and a ready CaseWare location where users can manage the job's documents.
