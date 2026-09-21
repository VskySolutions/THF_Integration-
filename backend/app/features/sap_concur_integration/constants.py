from enum import Enum


class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
