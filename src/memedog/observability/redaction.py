"""Global logging filter that scrubs API keys / tokens from log output."""
from __future__ import annotations

import logging
import re

# Pattern-based redaction (applied to every log message).
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(api-key=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    (re.compile(r"bot\d+:[A-Za-z0-9_\-]+"), "bot***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1***"),
]

_SECRET_ATTRS = (
    "helius_api_key",
    "rugcheck_api_key",
    "twitter_bearer",
    "openai_api_key",
    "anthropic_api_key",
    "deepseek_api_key",
    "telegram_bot_token",
    "telegram_api_hash",
)


class SecretRedactingFilter(logging.Filter):
    """Scrub secret patterns and exact secret values from log records.

    Always returns True (never drops a record); only rewrites the text.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 8]

    def _scrub(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        for pat, repl in _PATTERNS:
            text = pat.sub(repl, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            scrubbed = self._scrub(msg)
            if scrubbed != msg:
                record.msg = scrubbed
                record.args = ()
        except Exception:
            # Logging must never crash the app.
            pass
        return True


def install_redaction(settings=None) -> SecretRedactingFilter:
    """Install a SecretRedactingFilter on the root logger and its handlers.

    Handler-level installation is what catches records that propagate up from
    child loggers (logger-level filters only see records logged directly).
    """
    secrets: list[str] = []
    if settings is not None:
        for name in _SECRET_ATTRS:
            val = getattr(settings, name, None)
            if val:
                secrets.append(str(val))
    filt = SecretRedactingFilter(secrets=secrets)
    root = logging.getLogger()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
    return filt
