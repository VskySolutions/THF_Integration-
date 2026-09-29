# Maconomy to CCH/XCM Integration - Conference Q&A

## Quick overview

Maconomy holds engagement and customer information, while CCH/XCM is used to manage tax workflow tasks. Creating and linking the same tax engagement manually in both systems takes time and can result in missing links or duplicate tasks.

This integration finds eligible tax engagements in Maconomy, searches CCH/XCM for a matching task, creates a task when no match exists, and saves the CCH/XCM task reference back in Maconomy.

**Simple message for visitors:** Maconomy supplies the tax engagement information. CCH/XCM manages the workflow task. The integration connects the two records and avoids unnecessary task creation.

## How it works

1. Find recent, open tax engagements in Maconomy that are not yet linked to CCH/XCM.
2. Read the customer, tax task type, engagement year, and fiscal year-end information.
3. Calculate the period-end date needed for CCH/XCM.
4. Search CCH/XCM using the customer account, task type, and period-end date.
5. Link one matching task, or create a new task when no match exists.
6. If several matches are found, stop and request manual review.
7. Save the CCH/XCM task reference and period-end date back in Maconomy.
8. Record the result for business and support teams.

> **Key point:** This is not a full two-way synchronization. Engagement information moves from Maconomy to CCH/XCM, and the resulting CCH/XCM task reference is written back to Maconomy.

## Questions business and functional visitors may ask

### 1. What business problem does this integration solve?

It reduces the manual work needed to create or link tax workflow tasks. It also lowers the risk of duplicate CCH/XCM tasks and makes the relationship between a Maconomy engagement and its workflow task easier to track.

### 2. What is the main business value?

The key benefits are faster engagement setup, fewer duplicate tasks, consistent task matching, clearer exceptions, and better visibility across finance and tax operations.

### 3. Which system is the source of the engagement information?

Maconomy is the source for the eligible engagement, customer number, tax work type, and year information used by this flow. CCH/XCM remains the system where the workflow task is managed.

### 4. Is this a two-way synchronization?

Not in the general sense. Maconomy sends the information needed to find or create a CCH/XCM task. The CCH/XCM task reference is then saved in Maconomy, but other CCH/XCM task details are not synchronized back.

### 5. Which Maconomy engagements are included?

The current flow selects recent engagements that are open, are not templates, belong to the TAX location, and do not already contain a CCH/XCM task reference.

### 6. Why are only unlinked engagements selected?

Once an engagement has a saved CCH/XCM task reference, it is treated as already mapped. This prevents the same engagement from repeatedly entering the task-creation process.

### 7. How does the integration find the correct CCH/XCM task?

It searches using three business values: the customer account number, the task type, and the period-end date. Together, these values identify the expected tax workflow task.

### 8. How is the period-end date decided?

The integration combines the engagement year with the customer's fiscal year-end month and uses the final day of that month. For example, a December year-end for 2026 becomes December 31, 2026.

### 9. Where does the CCH/XCM task type come from?

The Maconomy engagement contains a tax work classification. The integration uses the approved description linked to that classification as the CCH/XCM task type.

### 10. What happens when no matching task exists in CCH/XCM?

The integration creates a new CCH/XCM task using the customer account, task type, period-end date, and a description containing the Maconomy engagement number.

### 11. What happens when exactly one matching task exists?

The existing task is linked to the Maconomy engagement. No duplicate task is created.

### 12. What happens when several matching tasks exist?

The integration does not guess which task is correct. It marks the engagement for manual review and does not save a task link until the conflict is resolved.

### 13. How does it prevent duplicate CCH/XCM tasks?

It always searches before creating. A new task is created only when the search returns no matching task.

### 14. What is saved back in Maconomy?

The integration saves the selected or newly created CCH/XCM task reference and the calculated period-end date. This creates a visible link for later business processes.

### 15. Can it overwrite a link that someone added during the run?

No. Before saving, it checks that the Maconomy engagement has not changed and still has no task reference. If it changed, the write is stopped and reported for review.

### 16. What happens if required business information is missing?

The engagement is reported as Failed. Examples include a missing customer number, task type, engagement year, fiscal year-end month, or period-end date. The information can be corrected and the engagement retried.

### 17. Will one bad engagement stop all other engagements?

Normally, no. A problem with one engagement is recorded and processing continues for the others. A full run may stop if Maconomy or CCH/XCM cannot be accessed.

### 18. Can one engagement be retried separately?

Yes. A user can retry one eligible Maconomy job by its job number. This supports correction and recovery without rerunning the full group.

### 19. What results will the business team see?

- **Linked:** One existing CCH/XCM task was found and linked.
- **Created:** A new CCH/XCM task was created and linked.
- **Updated:** The task reference was successfully saved in Maconomy.
- **Manual review:** Several possible matches were found.
- **Failed:** Information was missing or a system action could not be completed.

### 20. Is there an audit trail?

Yes. Each run records its overall status and counts for engagements found, tasks linked, tasks created, Maconomy records updated, manual-review items, and failures. Failed and manual-review engagement details are also retained.

### 21. Can business users view the results?

Yes. The application includes a dashboard showing recent runs and their main results. It also provides a single-job sync option for an eligible engagement.

### 22. Does it run automatically?

It can. When the application scheduler is enabled, the process runs at a configurable interval; the current default is every five minutes. It can also be started on demand.

### 23. What happens if Maconomy or CCH/XCM is unavailable?

The run records a failure and can be tried again after service is restored. The saved task-reference check and search-before-create rule help make retries safer.

### 24. Does this integration create customers in CCH/XCM?

No. The customer account is expected to exist and to use the same agreed account number. Missing or inconsistent customer setup must be corrected through the normal business process.

### 25. Does it synchronize employee time into CCH/XCM?

No. The current implemented scope covers tax engagement task matching, creation, and linking. Time-entry synchronization is not part of this current flow.

### 26. Does it keep every CCH/XCM task change synchronized with Maconomy?

No. The current purpose is to establish the task link. Ongoing task status, assignment, due-date, completion, or other workflow changes are outside the current scope.

### 27. How is access controlled?

Only approved system requests can start the integration. The integration must also be enabled, and access to both Maconomy and CCH/XCM depends on configured accounts and permissions.

### 28. Can it support a large number of engagements?

It processes engagements individually within a controlled batch. The current batch limit is 2,000 Maconomy records, so expected volumes and run frequency should be confirmed during implementation planning.

### 29. What must the customer confirm before go-live?

The customer should confirm customer-number alignment, tax task-type mappings, fiscal year-end data, task ownership, run frequency, system permissions, and the team responsible for manual-review items. Existing duplicate CCH/XCM tasks should also be reviewed.

### 30. Who should own the process after go-live?

A tax operations or support owner should monitor results, resolve multiple matches or missing data, and retry corrected engagements. Clear ownership prevents exceptions from remaining unresolved.

### 31. Can the integration be expanded later?

Yes. Future phases can consider additional engagement types, task updates, time information, or other workflow events after the business rules, ownership, and system mappings are agreed.

### 32. What type of organization benefits most from this integration?

It is most valuable for firms using Maconomy to manage engagements and CCH/XCM to manage tax workflows, especially where teams currently create and link many tax tasks by hand.

## Closing statement

The Maconomy to CCH/XCM integration provides a controlled and traceable way to connect tax engagements with workflow tasks. Its value is straightforward: less manual setup, fewer duplicate tasks, reliable linking, and clear handling of business exceptions.
