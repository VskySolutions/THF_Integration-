from enum import Enum


class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIALLY_SUCCESS = "PARTIALLY_SUCCESS"


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    RETRY_CREATE = "RETRY_CREATE"


class ProcessingStage(str, Enum):
    # Stored as Text (NOT a PG enum) on sap_concur_invoice_integration_logs —
    # values defined here, mirroring sap_concur_integration/constants.py.
    INVOICE_FETCH = "INVOICE_FETCH"
    JOURNAL_CREATION = "JOURNAL_CREATION"
    INVOICE_ALLOCATION_LINE_CREATION = "INVOICE_ALLOCATION_LINE_CREATION"
    COMPLETED = "COMPLETED"
