from pydantic import BaseModel
from typing import Optional


class CustomerRequest(BaseModel):
    customer_numbers: Optional[list[str]] = None