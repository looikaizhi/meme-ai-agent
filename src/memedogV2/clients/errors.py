from __future__ import annotations

from typing import Optional


class DataSourceError(Exception):
    """gmgn-cli failed in a non-rate-limit way."""


class RateLimitBanned(Exception):
    """gmgn returned 429. reset_at is the unix ts when the ban lifts (if known)."""

    def __init__(self, message: str, reset_at: Optional[int] = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at
