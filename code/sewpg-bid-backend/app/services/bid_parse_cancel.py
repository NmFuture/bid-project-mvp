from __future__ import annotations


class ParseCancelledError(RuntimeError):
    """Raised when a tender parse run has been cancelled by the user."""
