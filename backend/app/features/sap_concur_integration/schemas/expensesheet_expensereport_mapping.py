import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.features.sap_concur_integration.constants import IntegrationStatus


class ExpenseReportExpenseSheetMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    maconomy_employee_number: str | None = None
    maconomy_expensesheet_no: str
    sap_concur_expensereport_id: str 
    expense_line_metadata: dict | None = None
    submitted: IntegrationStatus | None = None
    approved: IntegrationStatus | None = None
    created_on_utc: datetime
    updated_on_utc: datetime | None
