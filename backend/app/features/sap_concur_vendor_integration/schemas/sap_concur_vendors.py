from pydantic import BaseModel, Field


class RetryVendorSyncRequest(BaseModel):
    vendor_code: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="SAP Concur vendor code to retry into Maconomy",
    )
