"""Live Telegram test — sends a REAL message. Double-gated to avoid accidents.

Requires in .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
AND environment variable MEMEDOG_LIVE_TELEGRAM=1 (explicit opt-in to actually send).

Run with:
  MEMEDOG_LIVE_TELEGRAM=1 python -m pytest -m live tests/live/test_live_telegram.py -v
"""
import os
from datetime import datetime, timezone

import pytest

from memedog.alert import maybe_notify
from memedog.alert.telegram import TelegramAlert
from memedog.config import load_config
from memedog.models import Signal, SignalType

pytestmark = pytest.mark.live


def _require_telegram():
    cfg = load_config()
    if not (cfg.settings.telegram_bot_token and cfg.settings.telegram_chat_id):
        pytest.skip("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env")
    if os.environ.get("MEMEDOG_LIVE_TELEGRAM") != "1":
        pytest.skip("set MEMEDOG_LIVE_TELEGRAM=1 to actually send a real Telegram message")
    return cfg


async def test_live_telegram_direct_send():
    cfg = _require_telegram()
    alert = TelegramAlert(
        bot_token=cfg.settings.telegram_bot_token,
        chat_id=cfg.settings.telegram_chat_id,
    )
    try:
        ok = await alert.send("✅ MemeDog Radar live test (test_live_telegram_direct_send)")
        assert ok is True
    finally:
        await alert.aclose()


async def test_live_maybe_notify_sends_bullish():
    cfg = _require_telegram()
    sig = Signal(
        mint="LiveTestMint", symbol="LIVEDOG", signal=SignalType.BULLISH, confidence=0.9,
        score_total=82.0, bull_points=["live test"], bear_points=[], red_flags=[],
        rationale="live test signal", created_at=datetime.now(timezone.utc), trace_id="live-tg",
    )
    sent = await maybe_notify(sig, cfg)
    assert sent is True
