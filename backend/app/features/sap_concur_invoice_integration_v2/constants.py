from enum import Enum


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    RETRY_CREATE = "RETRY_CREATE"


class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIALLY_SUCCESS = "PARTIALLY_SUCCESS"


class InvoiceActionStatus(str, Enum):
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


class ProcessingStage(str, Enum):
    INVOICE_FETCH = "INVOICE_FETCH"
    INVOICE_CREATION = "INVOICE_CREATION"
    LINE_CREATION = "LINE_CREATION"
    SUBMISSION = "SUBMISSION"
    APPROVAL = "APPROVAL"
    COMPLETED = "COMPLETED"


__all__ = ["IntegrationAction", "IntegrationStatus", "InvoiceActionStatus", "ProcessingStage"]
