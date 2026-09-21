from enum import Enum


class IntegrationRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class IntegrationTriggerType(str, Enum):
    API = "API"
    SCHEDULER = "SCHEDULER"
