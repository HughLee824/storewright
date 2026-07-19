"""Classified application errors."""


class ShopScoutError(Exception):
    """Base application error."""


class ManualActionRequiredError(ShopScoutError):
    """A login or verification page requires a human."""


class InvalidImageError(ShopScoutError):
    """Downloaded content is not an acceptable image."""


class VisionProviderError(ShopScoutError):
    """Vision request failed with a classified code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
