# CCH/XCM Field Mapping

| SourceField | TargetField | PurposeOfField |
|---|---|---|
| `jobs.jobnumber` | `Client.accountNumber` | Provides the unique client reference in CCH. It is also used to check whether the client already exists and prevent duplicate creation. |
| `specification1.description` | `Client.clientType` | Determines whether the CCH Client is created as `Individual` or `Entity`. The value `individual` creates an Individual; all other values create an Entity. |
| `jobs.name1` | `Client.last_Entity_Name` | Provides the organization name for an Entity Client. It is also used as the client name when an Individual does not have both a first name and last name. |
| `customers.customerremark27` | `Client.firstName` | Provides the client's first name when the Client is an Individual and both first name and last name are available. |
| `customers.customerremark28` | `Client.middleName` | Provides the Individual client's middle name when it is available. This field is optional. |
| `customers.customerremark29` | `Client.last_Entity_Name` | Provides the Individual client's last name. It is used when both first name and last name are available. |
| `customers.customerremark30` | `Client.suffix` | Provides a name suffix such as `Jr.`, `Sr.`, or `III` for an Individual client. This field is optional. |
| `employees.electronicmailaddress` | `Client.responsiblePerson` | Provides the Billing Manager's email address. The employee is identified using `jobs.employeenumber6`. |
| `jobs.electronicmailaddress` | `Client.emailId` | Stores the client's email address in CCH so the available contact information is included with the Client record. |
| `jobs.telephone` | `Client.phoneNumber` | Stores the client's telephone number in CCH. This field is left empty when no telephone number is available. |
| `specification2.description` | `Client.primaryTask` | Provides the tax Return Type as the Client's primary task, helping CCH identify the main type of tax work for the client. |
| `jobs.theyear + customers.fiscalyearendmonth` | `Client.periodEndDate` | Calculates the final day of the client's fiscal year-end month for the engagement year. For example, December 2026 becomes `12/31/2026`. |
| `employees.electronicmailaddress` | `Client.auditPartner` | Provides the CSE or Engagement Executive's email address. The employee is identified using `jobs.specification5name`. |
| `employees.electronicmailaddress` | `Client.taxPartner` | Provides the Engagement Partner's email address. The employee is identified using `jobs.purposename`. |
| `Hardcode "HQ"` | `Client.originatingLocationName` | Assigns the newly created Client to the standard originating location named `HQ`. |
| `Hardcode "Y"` | `Client.active` | Marks the newly created Client as active so it can be used for CCH work and Task creation. |
| `jobs.jobnumber` | `Task.accountNumber` | Connects the newly created Task to the correct CCH Client using the same engagement number. |
| `specification2.description` | `Task.taskType` | Provides the tax Return Type for the Task, such as the applicable tax filing or service type. |
| `jobs.theyear + customers.fiscalyearendmonth` | `Task.periodEndDate` | Provides the Task period-end date using the last day of the fiscal year-end month. A time value of `00:00:00` is added when sent to CCH. |
| `jobs.description1` | `Task.taskDescription` | Provides the engagement description as the Task description so users can understand the purpose of the Task. |
| `jobs.jobnumber` | `Task.taskDescription` | Used as the Task description only when `jobs.description1` is blank, ensuring that every created Task has a description. |
