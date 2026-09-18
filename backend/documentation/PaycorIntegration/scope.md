# Paycor to Maconomy Employee Integration

## Purpose

This integration sends employee information from Paycor to Maconomy.

Paycor is the main system where employee information is maintained. Maconomy receives the employee information needed for its business processes.

The integration will create new employees and update selected information for existing employees. Information will move only from Paycor to Maconomy.

## 1. How decisions are made

### Creating a new employee

The integration will select active employees whose hire date is today or yesterday.

It will make the following decisions for each employee:

1. It will check whether the required employee information is available in Paycor.
2. It will check whether the employee already exists in Maconomy.
3. If the employee does not exist, it will create the employee in Maconomy.
4. If the employee already exists, it will not create another record.
5. If the employee number does not match between Paycor and Maconomy, it will stop processing that employee and ask for a manual review.
6. If Maconomy accepts the employee, the result will be shown as **Created**.
7. If Maconomy does not accept the employee, the result will be shown as **Failed**, together with the reason.

### Updating an existing employee

The integration will compare selected employee information in Paycor and Maconomy.

- If the information is the same, no change will be made. The result will be shown as **Skipped**.
- If the information is different, Maconomy will be updated. The result will be shown as **Updated**.
- If the employee cannot be matched correctly, no change will be made. The result will be shown as **Failed** and will need a manual review.

If one employee has a data problem, the integration will continue with the other employees. If Paycor or Maconomy is unavailable, the full run may stop and need to be started again later.

## 2. Employee information used in the flow

The employee number will be the main reference used to identify the same employee in Paycor and Maconomy. The employee number is expected to be the same in both systems.

### Information used when an employee is created

| Information in Paycor | Information in Maconomy |
| --- | --- |
| Employee number | Employee number |
| Employee identity | Paycor employee reference |
| First and last name | Employee name |
| First name | First name |
| Middle name | Middle name |
| Last name | Last name |
| Country | Country |
| Hire date | Date employed |
| Work email address | Email address |
| Job title | Position |
| Work location name | Work location description |
| Personal title | Personal title |
| Name suffix | Name suffix |

The employee name will be saved as `Last name, First name` when both names are available.

Only USA is currently supported. Other countries must be agreed before they can be included.

### Information updated for an existing employee

The following information can be updated in Maconomy:

- Employee name
- Country
- Hire date
- Work email address
- Job title

Department details, job codes, and work location numbers are not currently sent to Maconomy.

## 3. How the integration will run

The integration can be run in three ways:

1. **Recent hire run:** It will process active employees whose hire date is today or yesterday.
2. **Employee update run:** It will review employees who exist in both systems and update information that has changed.
3. **Single employee run:** It will process one employee. This can be used for a correction or a retry.

The Paycor integration does not currently run automatically within the application. An approved business process or an external scheduling service must start it.

Before production use, the business must agree on how often it will run. The suggested approach is:

- Run the recent hire process once every day.
- Run the employee update process at an agreed time.
- Use the single employee process when a correction or retry is needed.

After every run, the result for each employee will be shown as **Created**, **Updated**, **Skipped**, or **Failed**. Failed employees should be reviewed and processed again after the problem has been corrected.

## 4. What is not included

The following items are not included in the current scope:

- Sending information from Maconomy back to Paycor.
- Creating or changing employee information in Paycor.
- Processing employee termination, suspension, rehire, or deletion.
- Processing inactive employees.
- Processing payroll, salary, tax, benefit, bank, time, attendance, or leave information.
- Processing employee documents, attachments, emergency contacts, or dependent information.
- Creating departments, work locations, companies, or organization structures in Maconomy.
- Correcting conflicting employee numbers automatically.
- Combining duplicate employee records automatically.
- Supporting countries other than USA.
- Moving old employee records that are outside the active employee list.
- Sending changes immediately every time an employee is changed in Paycor.

## 5. What is needed before the integration can run

The following items must be ready:

- The integration must have permission to read employee information from Paycor.
- The integration must have permission to create and update employees in Maconomy.
- The correct Paycor organization must be selected.
- The integration must be turned on for the required system.
- Employee numbers must be unique.
- Employee numbers must be suitable for use in both Paycor and Maconomy.
- Required employee information must be complete in Paycor.
- Country information must use an agreed value.
- Existing duplicate or conflicting employee records should be reviewed before the first run.
- The business must agree on the run time, the support owner, and the process for reviewing failures.

## 6. Important points to consider

- Paycor will be treated as the main system for the employee information listed in this document.
- Only active Paycor employees will be processed.
- The recent hire process will use the hire date. It will include only today and yesterday.
- An older employee can be processed separately when needed.
- The employee number must match in Paycor and Maconomy.
- An employee will not be created again when a matching record already exists in Maconomy.
- Conflicting employee information will not be changed automatically. It must be reviewed.
- Only USA is currently supported.
- The work email rules must be confirmed before production use.
- The employee update run will review all relevant active employees and will skip employees who have no changes.
- A temporary Paycor or Maconomy problem may require the process to be run again.
- A person must be responsible for reviewing failed employees and arranging corrections.
- The run times must be agreed because the integration is not currently started automatically by the application.

## Summary

This integration provides a controlled way to create and update Maconomy employees using information from Paycor. It checks for existing employees, avoids creating duplicate records, updates only the agreed information, and clearly reports employees that need attention.
