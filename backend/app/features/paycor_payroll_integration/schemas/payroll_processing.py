"""Schemas for Paycor Payroll Processing."""

from typing import Any
from pydantic import BaseModel, Field


class PayrollProcessingParams(BaseModel):
    from_check_date: str | None = Field(
        default=None,
        alias="fromCheckDate",
        description="Filter from check date in format: YYYY-MM-DDTHH:MM:SS. Defaults to current date if omitted.",
    )
    to_check_date: str | None = Field(
        default=None,
        alias="toCheckDate",
        description="Optional filter to check date in format: YYYY-MM-DDTHH:MM:SS",
    )
    include_other_payruns: str = Field(
        default="All",
        alias="includeOtherPayruns",
        description="Options: 'All', 'A' = Additional Payruns, 'J' = Adjustment Payrun",
    )
    continuation_token: str | None = Field(
        default=None,
        alias="continuationToken",
        description="Continuation token for pagination",
    )


class PayrollProcessingResponse(BaseModel):
    has_more: bool | None = None
    continuation_token: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
