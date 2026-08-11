from pydantic import BaseModel, Field


class CreateCasewareJobRequest(BaseModel):
    jobnumber: str = Field(min_length=1)
