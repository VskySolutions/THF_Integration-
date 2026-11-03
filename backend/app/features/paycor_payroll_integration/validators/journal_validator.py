"""Validation utilities for Paycor Payroll to Maconomy Journal sync."""

from typing import Any


def validate_journal_payload(
    card_data: dict[str, Any],
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Validate whether a journal should be created in Maconomy.

    Returns a structured payload containing:
      - should_create: bool (True if valid and lines > 0, else False)
      - create: "yes" | "no"
      - lines_count: int
      - skip_reason: str | None
      - card_data: dict (clean card header for Maconomy)
      - lines: list (clean lines for Maconomy)
    """
    lines_count = len(lines) if lines else 0

    if lines_count == 0:
        return {
            "should_create": False,
            "create": "no",
            "lines_count": 0,
            "skip_reason": "No line items present for this department journal.",
            "card_data": card_data,
            "lines": [],
        }

    return {
        "should_create": True,
        "create": "yes",
        "lines_count": lines_count,
        "skip_reason": None,
        "card_data": card_data,
        "lines": lines,
    }

