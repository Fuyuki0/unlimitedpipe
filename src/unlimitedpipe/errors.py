"""Exceptions with messages meant for humans.

Every error the CLI prints comes from one of these. ``hint`` tells the user what to try next.
"""

from __future__ import annotations


class UnlimitedError(Exception):
    """Base class for expected, user-facing errors."""

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(UnlimitedError):
    """The command was called the wrong way."""

    exit_code = 2


class ConfigError(UnlimitedError):
    """A pipeline file or component option is invalid."""

    exit_code = 2


class ExpressionError(UsageError):
    """A filter/map expression could not be parsed."""


class InputError(UnlimitedError):
    """Input events (usually stdin) could not be read."""


class FetchError(UnlimitedError):
    """A network request failed."""

    def __init__(self, message: str, *, url: str, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.url = url


class RobotsDisallowed(FetchError):
    """robots.txt does not allow fetching this URL."""
