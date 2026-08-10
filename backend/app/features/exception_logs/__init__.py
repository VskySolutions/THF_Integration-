"""Centralized exception logging shared by every API feature."""

from app.features.exception_logs.handlers import install_exception_logging

__all__ = ["install_exception_logging"]
