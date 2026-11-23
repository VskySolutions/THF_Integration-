from pydantic import BaseModel


class RetryInvoiceSyncRequest(BaseModel):
    invoice_id: str
