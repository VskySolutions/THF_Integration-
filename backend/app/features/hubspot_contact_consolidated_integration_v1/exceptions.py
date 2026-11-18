"""Errors raised while reading Maconomy for the v1 integration."""


class MaconomyError(Exception):
    """Safe message plus context for troubleshooting a Maconomy failure."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        reason: str,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason
        self.upstream_status = upstream_status
