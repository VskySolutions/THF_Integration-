"""Integration errors with safe context for troubleshooting."""


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


class HubSpotError(Exception):
    """HubSpot Company upsert failure without request credentials or payload."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        upstream_status: int | None = None,
        batch_number: int | None = None,
        category: str | None = None,
        correlation_id: str | None = None,
        upstream_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.upstream_status = upstream_status
        self.batch_number = batch_number
        self.category = category
        self.correlation_id = correlation_id
        self.upstream_message = upstream_message
