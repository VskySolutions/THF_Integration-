"""Constants for Paycor Payroll Integration."""

from enum import Enum

PAYCOR_PAYROLL_ROUTER_PREFIX = "/paycor/payroll"
PAYCOR_PAYROLL_TAG = "paycor-payroll-integration"


class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
