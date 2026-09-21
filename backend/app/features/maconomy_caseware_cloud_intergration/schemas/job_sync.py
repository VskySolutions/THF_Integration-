from pydantic import BaseModel, field_validator


class SyncJobRequest(BaseModel):
    """Request body for synchronizing one Maconomy job."""

    jobnumber: str

    @field_validator("jobnumber")
    @classmethod
    def validate_jobnumber(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("jobnumber is required")
        return value
