"""Classified application errors."""


class CatalogScoutError(Exception):
    """Base application error."""


class ManualActionRequiredError(CatalogScoutError):
    """A login or verification page requires a human."""


class RiskCooldownRequiredError(CatalogScoutError):
    """Detail navigation must pause until the persisted safety cooldown expires."""

    def __init__(self, reason: str, retry_at: str) -> None:
        super().__init__(f"{reason}; retry after {retry_at}")
        self.reason = reason
        self.retry_at = retry_at


class InvalidImageError(CatalogScoutError):
    """Downloaded content is not an acceptable image."""


class VisionProviderError(CatalogScoutError):
    """Vision request failed with a classified code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
