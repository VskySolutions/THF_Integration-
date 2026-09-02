from pydantic import BaseModel, Field


class CreateCCHJobRequest(BaseModel):
    jobnumber: str = Field(min_length=1)
