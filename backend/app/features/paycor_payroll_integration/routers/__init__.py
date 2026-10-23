"""Routers package for Paycor Payroll Integration."""

from app.features.paycor_payroll_integration.routers.payroll_processing import router as payroll_processing_router

__all__ = ["payroll_processing_router"]
