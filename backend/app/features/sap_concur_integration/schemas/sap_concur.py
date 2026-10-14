from pydantic import BaseModel, Field


class ExpenseReportEmailRequest(BaseModel):
    email_id: str = Field(..., description="Email ID of the user")


class RetryExpenseReportRequest(BaseModel):
    report_id: str = Field(
        ..., min_length=1, description="SAP Concur expense report ID to retry"
    )

