class ConsolidationError(Exception):
    pass


class MaconomyError(ConsolidationError):
    """Raised when Maconomy discovery, stamping, or write-back fails."""


class MaconomyRecordNotFoundError(MaconomyError):
    """Raised when a requested Maconomy record does not exist."""


class MaconomyVersionConflictError(MaconomyError):
    """Raised when a Maconomy record changes before its write-back commit."""


class MaconomyMasterConflictError(MaconomyError):
    """Raised when members of one email group disagree about their master."""


class HubSpotError(ConsolidationError):
    """Raised when a HubSpot API request fails."""


class HubSpotAuthError(HubSpotError):
    """Raised when HubSpot rejects the configured service key."""


class HubSpotConfigError(HubSpotError):
    """Raised when the HubSpot service key is missing."""
