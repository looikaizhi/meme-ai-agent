"""Telegram alert client and notification gate for MemeDog Radar.

Usage::

    from memedog.alert.telegram import TelegramAlert, maybe_notify

    # Low-level: send any text
    client = TelegramAlert(bot_token="...", chat_id="...")
    await client.send("Hello from MemeDog!")

    # High-level: respect config filters
    sent = await maybe_notify(signal, cfg)
"""
from __future__ import annotations

import logging

from memedog.clients.base import BaseHTTPClient, DataSourceError
from memedog.models import Signal

logger = logging.getLogger(__name__)


class TelegramAlert(BaseHTTPClient):
    """Thin wrapper around the Telegram Bot sendMessage endpoint.

    Inherits retry/backoff logic from ``BaseHTTPClient``.

    Parameters
    ----------
    bot_token:
        The Telegram bot token (from BotFather).
    chat_id:
        Target chat / channel id (may be a numeric string or @username).
    timeout, max_retries, backoff_base:
        Forwarded to ``BaseHTTPClient``.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.2,
    ) -> None:
        super().__init__(
            base_url="https://api.telegram.org",
            timeout=timeout,
            max_retries=max_retries,
            backoff_base=backoff_base,
        )
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send(self, text: str) -> bool:
        """Send *text* to the configured chat.

        Returns ``True`` on success.
        Raises ``DataSourceError`` on network / API failure (after retries).
        """
        url = f"/bot{self._bot_token}/sendMessage"
        await self.post_json(url, json={"chat_id": self._chat_id, "text": text})
        return True


# ---------------------------------------------------------------------------
# High-level notification gate
# ---------------------------------------------------------------------------


def _format_message(signal: Signal) -> str:
    """Format a human-readable Telegram message from a Signal."""
    red_flags_text = (
        "\n  ⚑ " + "\n  ⚑ ".join(signal.red_flags) if signal.red_flags else "none"
    )
    bull_text = (
        "\n  + " + "\n  + ".join(signal.bull_points) if signal.bull_points else "none"
    )
    bear_text = (
        "\n  - " + "\n  - ".join(signal.bear_points) if signal.bear_points else "none"
    )
    return (
        f"[MemeDog] {signal.signal.value} — {signal.symbol}\n"
        f"Confidence: {signal.confidence:.0%}  |  Score: {signal.score_total:.1f}/100\n"
        f"\nBull points:{bull_text}\n"
        f"Bear points:{bear_text}\n"
        f"Red flags: {red_flags_text}\n"
        f"Mint: {signal.mint}"
    )


async def maybe_notify(
    signal: Signal,
    cfg,
    client: TelegramAlert | None = None,
) -> bool:
    """Conditionally send a Telegram alert based on config filters.

    Returns ``True`` if the message was sent; ``False`` otherwise.
    Never raises — errors are swallowed and logged.

    Parameters
    ----------
    signal:
        The Signal to potentially alert on.
    cfg:
        A ``Config`` (or compatible duck-typed) object with ``cfg.alert``
        (AlertConfig) and ``cfg.settings`` (Settings).
    client:
        Optional pre-built ``TelegramAlert`` to use.  If *None* and all
        checks pass, one is built from ``cfg.settings``.
    """
    # --- gate 1: feature enabled ---
    if not cfg.alert.enabled:
        logger.debug("maybe_notify: alert disabled, skipping")
        return False

    # --- gate 2: credentials present ---
    token = cfg.settings.telegram_bot_token
    chat_id = cfg.settings.telegram_chat_id
    if not token or not chat_id:
        logger.debug("maybe_notify: missing telegram credentials, skipping")
        return False

    # --- gate 3: signal type filter ---
    if signal.signal.value != cfg.alert.only_signal:
        logger.debug(
            "maybe_notify: signal %s != only_signal %s, skipping",
            signal.signal.value,
            cfg.alert.only_signal,
        )
        return False

    # --- gate 4: confidence threshold ---
    if signal.confidence < cfg.alert.min_confidence:
        logger.debug(
            "maybe_notify: confidence %.2f < min %.2f, skipping",
            signal.confidence,
            cfg.alert.min_confidence,
        )
        return False

    # --- build client if not provided ---
    if client is None:
        client = TelegramAlert(bot_token=token, chat_id=chat_id)

    # --- send ---
    try:
        text = _format_message(signal)
        await client.send(text)
        logger.info("Telegram alert sent for %s (%s)", signal.symbol, signal.signal.value)
        return True
    except DataSourceError as exc:
        logger.warning("maybe_notify: failed to send alert: %s", exc)
        return False
