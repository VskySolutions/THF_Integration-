MACONOMY_CCH_SYNC_PATH = "/api/v1/xcm-cch-client-scoped/sync"
MACONOMY_CASEWARE_SYNC_PATH = "/api/v1/maconomy-caseware-cloud/sync-jobs"
MACONOMY_CCH_SYNC_JOB_ID = "maconomy_cch_sync"
MACONOMY_CASEWARE_SYNC_JOB_ID = "maconomy_caseware_cloud_sync"

PAYCOR_CREATE_SYNC_PATH = (
    "/api/v1/paycor/sync-recent-hires-with-maconomy"
)
PAYCOR_UPDATE_SYNC_PATH = (
    "/api/v1/paycor/sync-updated-employees-with-maconomy"
)
PAYCOR_CREATE_SYNC_JOB_ID = "paycor_create_employee_sync"
PAYCOR_UPDATE_SYNC_JOB_ID = "paycor_update_employee_sync"
SAP_CONCUR_EXPENSE_SYNC_PATH = "/api/v1/sap-concur/sync-sap-concur-expense-reports-with-maconomy"
SAP_CONCUR_EXPENSE_SYNC_JOB_ID = "sap_concur_expense_sync"

# SAP Concur Employee Sync (5-minute scheduler)
SAP_CONCUR_EMPLOYEE_SYNC_PATH = "/api/v1/sap-concur-employees/sync-cycle"
SAP_CONCUR_EMPLOYEE_SYNC_JOB_ID = "maconomy_sap_concur_employee_sync"

HUBSPOT_SYNC_PATH = "/api/v1/hubspot/sync/customers"
HUBSPOT_SYNC_JOB_ID = "maconomy_hubspot_sync"
PAYCOR_EASTERN_TIMEZONE = "America/New_York"
#Paycor Payroll
PAYCOR_PAYROLL_SYNC_PATH = "/api/v1/paycor/payroll/sync-payroll-to-maconomy"
PAYCOR_PAYROLL_SYNC_JOB_ID = "paycor_payroll_sync"
