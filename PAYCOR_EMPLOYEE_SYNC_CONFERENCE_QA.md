# Paycor Employee Sync with Maconomy - Conference Q&A

## Quick overview

Paycor holds employee HR data, while Maconomy needs matching employee records for its job and financial workflows. Entering the same new hire in both systems takes time and can lead to missing, delayed, or duplicate records.

This integration finds recent hires in Paycor, checks Maconomy before creating employees, and keeps selected Maconomy information aligned when Paycor information changes.

**Simple message for visitors:** Paycor is the source of truth for the employee information covered by this integration. Information flows from Paycor to Maconomy, not from Maconomy back to Paycor.

## How it works

1. Read active employees from the selected Paycor company.
2. Identify recent hires whose hire date is today or yesterday.
3. Match each person using the employee number and a saved link between the two systems.
4. Create the employee in Maconomy only when a matching record does not already exist.
5. For existing employees, compare the approved information and update only what has changed.
6. Report each outcome as Created, Updated, Skipped, or Failed.

> **Key point:** Maconomy is checked for existing employees and current values, but the integration does not send Maconomy employee information back to Paycor.

## Questions business and functional visitors may ask

### 1. What business problem does this integration solve?

It reduces the need to enter the same employee in two systems. This saves time, reduces manual mistakes, and helps new employees become available in Maconomy sooner.

### 2. What is the main business value?

The main benefits are faster employee setup, fewer duplicate records, more consistent information, and clear visibility when an employee needs attention.

### 3. Which system is the source of truth?

Paycor is the source of truth for the supported employee information. Maconomy receives new or changed information from Paycor.

### 4. Is information sent in both directions?

No. The current flow is one-way, from Paycor to Maconomy. It does not change employee information in Paycor using Maconomy data.

### 5. Which employees are included?

The integration reads active employees from the selected Paycor company. The recent-hire process focuses on employees whose hire date is today or yesterday.

### 6. Why are both today and yesterday checked?

This creates a small safety window in case a daily run is delayed or missed. An older employee can still be processed separately when needed.

### 7. How does it know that both systems contain the same employee?

The employee number is the main shared reference and is expected to match in Paycor and Maconomy. The integration also keeps a saved link between the two employee records.

### 8. How are duplicate employees prevented?

Before creating an employee, the integration checks whether the employee number or an existing link is already present. If a match exists, it does not create another employee.

### 9. What happens if the employee already exists in Maconomy?

The employee is not created again. When the employee number matches, the integration can save or complete the link between Paycor and Maconomy and report the creation as Skipped.

### 10. What employee information can be created in Maconomy?

The current setup can send the employee number, name, country, hire date, work email, job title, work-location description, personal title, name suffix, manager, and a Paycor employee reference. Blank optional information is not sent.

### 11. Which information is kept updated after creation?

The current update process covers:

- Employee name
- Country
- Hire date
- Work email address
- Job title

Other Maconomy information is left unchanged.

### 12. Does every run overwrite the Maconomy employee record?

No. The integration compares the approved information first. If it is already the same, no update is made. If something differs, only the approved fields are updated.

### 13. What happens to the employee's manager information?

The manager can be assigned during employee creation when that manager already exists in Maconomy. If the manager is not yet available, the employee can still be created and the manager can be reviewed later.

### 14. What happens when employee numbers conflict?

The integration does not guess or merge records automatically. It marks that employee as Failed and asks for a person to review the mismatch.

### 15. What happens if employee information is incomplete?

That employee is reported as Failed with a reason. The business team can correct the information and run that employee again.

### 16. Will one problem stop all other employees?

Normally, no. If one employee has a data problem, the integration records the failure and continues with the remaining employees. A full run may stop if Paycor or Maconomy is unavailable.

### 17. Can one employee be retried without running everyone again?

Yes. A single employee can be processed separately. This is useful for corrections, older hires, or retrying a previous failure.

### 18. What results will the business team see?

- **Created:** A new employee was added to Maconomy.
- **Updated:** Approved Maconomy information was changed using Paycor data.
- **Skipped:** The employee already existed or nothing needed to change.
- **Failed:** The employee needs correction or manual review.

### 19. Is there an audit trail?

Yes. The solution records the employee link and the result of each create or update attempt, including a status and message for review.

### 20. Is the synchronization real-time?

No. It runs as a controlled process for recent hires, existing-employee updates, or one selected employee. The customer can use an approved external schedule based on its business needs.

### 21. What happens if Paycor or Maconomy is temporarily unavailable?

The run may stop if the required information cannot be read. After service is restored, the process can be run again. Existing-record checks help make retries safe.

### 22. Does it handle inactive or terminated employees?

No. The current scope covers active employees. Termination, suspension, rehire, deletion, and inactive-employee processing are not included.

### 23. Does it transfer payroll or sensitive financial information?

No. It does not transfer salary, payroll, tax, benefits, bank details, time, attendance, leave, employee documents, emergency contacts, or dependant information.

### 24. Which countries are supported?

The current setup supports the USA. Additional countries can be considered after their country values and business rules are agreed and tested.

### 25. How is access controlled?

Only approved system-to-system requests can start the integration. Access to Paycor and Maconomy also depends on configured accounts and permissions.

### 26. Can the integration support a large employee list?

Yes. It can read the employee list in manageable groups and process eligible employees one at a time. Actual volume and run frequency should be confirmed during implementation planning.

### 27. What does the customer need before going live?

The customer should confirm employee-number rules, data quality, the information to be shared, system permissions, run frequency, and who will review failures. Existing duplicate or conflicting records should be resolved before the first production run.

### 28. Who should own the process after go-live?

A business or support owner should monitor results, correct failed employee data, and arrange retries. Clear ownership helps ensure that exceptions do not remain unresolved.

### 29. Can the scope be expanded later?

Yes. Additional fields, countries, schedules, or employee events can be considered as future enhancements after the business rules and system mappings are agreed.

### 30. What type of organization benefits most from this integration?

It is most useful for organizations that use Paycor for employee administration and Maconomy for operational or financial work, especially when manual employee setup is repetitive or error-prone.

## Closing statement

The Paycor employee sync provides a controlled and traceable way to create employees and maintain selected information in Maconomy. Its value is simple: less manual work, fewer duplicates, clearer exception handling, and a defined ownership model in which Paycor supplies the supported employee information and Maconomy consumes it.
