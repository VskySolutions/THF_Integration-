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


class Spec5CreationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class PurposeCreationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class SAPConcurUserCreationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class TimesheetSubmissionMode(str, Enum):
    APPEND = "APPEND"
    REPLACE = "REPLACE"


class TimesheetSubmissionStatus(str, Enum):
    SUBMITTING = "SUBMITTING"
    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
