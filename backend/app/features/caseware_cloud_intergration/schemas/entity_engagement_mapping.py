import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityEngagementMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caseware_cloud_entity_cwid: str
    maconomy_job_number: str
    maconomy_job_version_number: str | None
    cw_addresses: list[int] | None
    created_on_utc: datetime
    updated_on_utc: datetime | None
