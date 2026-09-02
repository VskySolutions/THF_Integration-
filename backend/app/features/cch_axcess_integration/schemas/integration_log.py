import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.features.cch_axcess_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)


class IntegrationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cch_axcess_entity_engagement_mapping_id: uuid.UUID | None
    instance: str
    base_url: str
    username: str
    status: IntegrationStatus
    message: str | None = None
    action: IntegrationAction
    jobnumber: str
    created_on_utc: datetime
