from enum import Enum

class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"


class EmpVendorCreationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"