"""Exception hierarchy for yahoo_finance_ai."""

from __future__ import annotations


class YahooError(Exception):
    """Base error for all yahoo_finance_ai failures."""


class AuthenticationError(YahooError):
    """Cookie/crumb session bootstrap or refresh failed."""


class RateLimitError(YahooError):
    """Yahoo throttled us (HTTP 429) and retries were exhausted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NotFoundError(YahooError):
    """Symbol not found or delisted."""


class ParseError(YahooError):
    """Unexpected response shape from Yahoo."""
