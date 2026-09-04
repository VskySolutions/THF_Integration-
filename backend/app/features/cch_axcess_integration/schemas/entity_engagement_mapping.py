import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityEngagementMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cch_axcess_entity_cchid: str
    maconomy_job_number: str
    maconomy_job_version_number: str | None
    created_on_utc: datetime
    updated_on_utc: datetime | None
