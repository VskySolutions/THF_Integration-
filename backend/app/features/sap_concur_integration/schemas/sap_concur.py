from pydantic import BaseModel, Field


class RetryExpenseReportRequest(BaseModel):
    report_id: str = Field(
        ..., min_length=1, description="SAP Concur expense report ID to retry"
    )

