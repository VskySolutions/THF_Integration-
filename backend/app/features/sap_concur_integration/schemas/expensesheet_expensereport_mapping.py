import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExpenseReportExpenseSheetMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caseware_cloud_entity_cwid: str
    maconomy_expensesheet_no: str
    sap_concur_expensereport_id: str 
    created_on_utc: datetime
    updated_on_utc: datetime | None
