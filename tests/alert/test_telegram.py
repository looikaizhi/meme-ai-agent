"""Tests for TelegramAlert and maybe_notify.

Strategy: inject a fake async client; no real network calls.
Tests are written before implementation (TDD - red first).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from memedog.models import Signal, SignalType


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_signal(
    signal: SignalType = SignalType.BULLISH,
    confidence: float = 0.85,
    score_total: float = 72.0,
) -> Signal:
    return Signal(
        mint="mint123",
        symbol="DOGE2",
        signal=signal,
        confidence=confidence,
        score_total=score_total,
        bull_points=["strong momentum", "low top10 pct"],
        bear_points=["new token"],
        red_flags=[],
        rationale="Looks good",
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        trace_id="trace-abc",
    )


def _make_cfg(
    enabled: bool = True,
    only_signal: str = "BULLISH",
    min_confidence: float = 0.6,
    bot_token: str | None = "BOT_TOKEN_123",
    chat_id: str | None = "CHAT_ID_456",
):
    """Build a minimal config-like object with alert, settings attrs."""
    alert = MagicMock()
    alert.enabled = enabled
    alert.only_signal = only_signal
    alert.min_confidence = min_confidence

    settings = MagicMock()
    settings.telegram_bot_token = bot_token
    settings.telegram_chat_id = chat_id

    cfg = MagicMock()
    cfg.alert = alert
    cfg.settings = settings
    return cfg


class FakeTelegramAlert:
    """Records calls to send(); returns a configurable result."""

    def __init__(self, return_value: bool = True, raise_error: Exception | None = None):
        self.send = AsyncMock(
            return_value=return_value,
            side_effect=raise_error,
        )
        self.calls: list[str] = []


# ---------------------------------------------------------------------------
# TelegramAlert.send tests
# ---------------------------------------------------------------------------


class TestTelegramAlertSend:
    """Unit-tests for TelegramAlert.send using respx mock."""

    @pytest.mark.asyncio
    async def test_send_returns_true_on_200(self):
        import respx
        import httpx
        from memedog.alert.telegram import TelegramAlert

        async with respx.MockRouter() as router:
            router.post("https://api.telegram.org/botTOKEN/sendMessage").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            client = TelegramAlert(bot_token="TOKEN", chat_id="CHAT", max_retries=1, backoff_base=0)
            result = await client.send("hello")
            assert result is True

    @pytest.mark.asyncio
    async def test_send_returns_false_on_error(self):
        import respx
        import httpx
        from memedog.alert.telegram import TelegramAlert
        from memedog.clients.base import DataSourceError

        async with respx.MockRouter() as router:
            router.post("https://api.telegram.org/botTOKEN/sendMessage").mock(
                return_value=httpx.Response(400, json={"ok": False})
            )
            client = TelegramAlert(bot_token="TOKEN", chat_id="CHAT", max_retries=1, backoff_base=0)
            with pytest.raises(DataSourceError):
                await client.send("hello")


# ---------------------------------------------------------------------------
# maybe_notify tests
# ---------------------------------------------------------------------------


class TestMaybeNotify:

    @pytest.mark.asyncio
    async def test_disabled_returns_false_no_send(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(enabled=False)
        fake_client = FakeTelegramAlert()
        result = await maybe_notify(_make_signal(), cfg, client=fake_client)
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(bot_token=None)
        fake_client = FakeTelegramAlert()
        result = await maybe_notify(_make_signal(), cfg, client=fake_client)
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_chat_id_returns_false(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(chat_id=None)
        fake_client = FakeTelegramAlert()
        result = await maybe_notify(_make_signal(), cfg, client=fake_client)
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_signal_type_mismatch_returns_false(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(only_signal="BULLISH")
        fake_client = FakeTelegramAlert()
        # Send a BEARISH signal when only BULLISH is desired
        result = await maybe_notify(
            _make_signal(signal=SignalType.BEARISH), cfg, client=fake_client
        )
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_confidence_below_min_returns_false(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(min_confidence=0.8)
        fake_client = FakeTelegramAlert()
        result = await maybe_notify(
            _make_signal(confidence=0.5), cfg, client=fake_client
        )
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_bullish_sends_and_returns_true(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(only_signal="BULLISH", min_confidence=0.6)
        fake_client = FakeTelegramAlert(return_value=True)
        result = await maybe_notify(
            _make_signal(signal=SignalType.BULLISH, confidence=0.85), cfg, client=fake_client
        )
        assert result is True
        fake_client.send.assert_called_once()
        # Verify the message text is meaningful
        msg = fake_client.send.call_args[0][0]
        assert "DOGE2" in msg
        assert "BULLISH" in msg

    @pytest.mark.asyncio
    async def test_datasource_error_returns_false_no_raise(self):
        from memedog.alert.telegram import maybe_notify
        from memedog.clients.base import DataSourceError

        cfg = _make_cfg(only_signal="BULLISH", min_confidence=0.6)
        fake_client = FakeTelegramAlert(raise_error=DataSourceError("network error"))
        # Should NOT raise; should return False
        result = await maybe_notify(
            _make_signal(signal=SignalType.BULLISH, confidence=0.85), cfg, client=fake_client
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_neutral_signal_with_only_bullish_config_returns_false(self):
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(only_signal="BULLISH")
        fake_client = FakeTelegramAlert()
        result = await maybe_notify(
            _make_signal(signal=SignalType.NEUTRAL), cfg, client=fake_client
        )
        assert result is False
        fake_client.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_generic_runtime_error_returns_false_no_raise(self):
        """Any non-CancelledError exception from send must be swallowed → False."""
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(only_signal="BULLISH", min_confidence=0.6)
        fake_client = FakeTelegramAlert(raise_error=RuntimeError("unexpected boom"))
        result = await maybe_notify(
            _make_signal(signal=SignalType.BULLISH, confidence=0.85), cfg, client=fake_client
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError must NOT be caught — it must propagate."""
        import asyncio
        from memedog.alert.telegram import maybe_notify

        cfg = _make_cfg(only_signal="BULLISH", min_confidence=0.6)
        fake_client = FakeTelegramAlert(raise_error=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await maybe_notify(
                _make_signal(signal=SignalType.BULLISH, confidence=0.85), cfg, client=fake_client
            )
