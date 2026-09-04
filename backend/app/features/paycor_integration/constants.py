from enum import Enum


class EmployeeStatus(str, Enum):
    INVITED = "INVITED"
    HIRED = "HIRED"


class IntegrationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IntegrationAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"