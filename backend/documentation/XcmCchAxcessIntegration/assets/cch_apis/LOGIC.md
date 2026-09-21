# Maconomy to CCH/XCM Integration - Logic

## Overview

Integration between Maconomy and CCH/XCM for:
1. Linking TAX engagements to CCH tasks
2. Syncing submitted time entries to CCH

---

## Part 1: Job Discovery & Task Mapping

### Trigger
- Run daily (or on-demand)
- Fetch jobs created in last 2 days

### Flow

```
Find TAX Jobs (last 2 days)
    │
    ├── LocationName = "TAX" (case-insensitive)
    ├── Closed = False
    ├── Template = False
    └── Text20 IS NULL or empty (not yet mapped)
    │
    ▼
┌─────────────────────────────────┐
│  For each job:                  │
│  1. Search CCH task            │
│  2. If found → Map             │
│  3. If not → Create → Map      │
└─────────────────────────────────┘
```

### Search CCH Task

```
Request:
{
  "accountNumber": CustomerNumber,
  "taskType": Specification2,
  "fromPeriodEndDate": PeriodEndDate,
  "toPeriodEndDate": PeriodEndDate
}

PeriodEndDate = LastDay(FiscalYearEndMonth, TheYear)
Example: December 2026 → 12/31/2026
```

### Handle Results

| Result | Action |
|--------|--------|
| 0 tasks found | Create new task in CCH |
| 1 task found | Map existing task |
| Multiple tasks | Send for manual review |

### Map Task to Maconomy

```
Write to Maconomy JobHeader:
- Text20 = CCH TaskInternalId
- Date5 = PeriodEndDate
```

---

## Part 2: Time Entry Sync

### Trigger
- Run every midnight
- Process all TAX engagements with mapped tasks

### Flow

```
Fetch Submitted Time Entries
    │
    ├── Submitted = True
    ├── Employee email exists
    └── Job has Text20 (TaskInternalId)
    │
    ▼
┌─────────────────────────────────┐
│  For each time entry:          │
│  1. Get Role from task line    │
│  2. Get Employee email         │
│  3. Calculate hours to send    │
│  4. Send to CCH                │
└─────────────────────────────────┘
```

### Time Entry Fields

| Field | Source | Description |
|-------|--------|-------------|
| EmployeeNumber | DailyTimesheetLine | Employee ID |
| JobNumber | DailyTimesheetLine | Job ID |
| TaskName | DailyTimesheetLine | Task name |
| NumberOf | DailyTimesheetLine | Hours worked |
| Submitted | DailyTimesheetLine | Must be True |
| Description | TaskListLine | **Role** |
| Email | Employee | Employee email |
| Text20 | JobHeader | TaskInternalId |

### Role Mapping

```
Role = TaskListLine.Description

Example:
- TaskListLine.Description = "Tax Preparation"
- Role sent to CCH = "Tax Preparation"
```

### Incremental Hours Calculation

```
HoursToSend = CurrentTotal - PreviouslySentTotal

Where:
- CurrentTotal = Sum of hours for (Employee + Job + Role)
- PreviouslySentTotal = Last successful sync amount
```

### Send to CCH

```
PUT /Task/{taskId}/actualtime/as

Request:
{
  "userEmail": Employee.Email,
  "time": HoursToSend
}

Where:
- taskId = JobHeader.Text20 (TaskInternalId)
- userEmail = Employee email
- time = Incremental hours
```

---

## Summary

### Part 1: Job Discovery & Mapping

```
Maconomy Job → Search CCH → Create/Link → Write Text20
```

### Part 2: Time Sync

```
Time Entry → Get Role (Description) → Get Email → Calculate Hours → Send to CCH
```

### Data Flow

```
┌─────────────┐         ┌─────────────┐
│   Maconomy  │         │   CCH/XCM   │
├─────────────┤         ├─────────────┤
│ JobHeader   │────────▶│ Task        │
│ - Text20    │◀────────│ - taskId    │
│ - Date5     │         │             │
├─────────────┤         ├─────────────┤
│ TimeEntry   │────────▶│ ActualTime  │
│ - Submitted │         │ - userEmail │
│ - NumberOf  │         │ - time      │
│ - Role      │         │             │
└─────────────┘         └─────────────┘
```

---

## Key Points

1. **Maconomy is authoritative** - Text20 holds the TaskInternalId
2. **Search before create** - Avoid duplicates
3. **Incremental hours only** - Send difference, not total
4. **Role from Description** - TaskListLine.Description = Role
5. **Email from Employee** - Must exist for time sync
