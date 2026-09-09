from pydantic import BaseModel, Field


class ExpenseReportEmailRequest(BaseModel):
    email_id: str = Field(..., description="Email ID of the user")

