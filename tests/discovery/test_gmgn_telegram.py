import asyncio
from types import SimpleNamespace

import pytest

from memedog.discovery.buffer import MintBuffer
from memedog.discovery.gmgn_telegram import (
    GMGNTelegramFeed,
    is_gmgn_launch_alert,
    normalize_telegram_chat_ref,
    normalize_telegram_chat_refs,
    parse_open_age_min,
    parse_gmgn_solana_alerts,
    parse_gmgn_solana_mints,
)

PUMP_MINT = "8yo564u5NKNzKV3jWQTSqSxXXFX69ALgweu4c8eapump"
BONK_MINT = "DezXAZ8z7PnrnRJjz3HfkqjFD3FqnJvqLqWZfC4e6T8"
AUTHOR = "A1xFe7U2rPnrnRJjz3HfkqjFD3FqnJvqLqWZfC4e6T"


def test_parse_gmgn_labeled_solana_mint():
    text = f"GMGN New Token Alert\nCA: {PUMP_MINT}\nChain: Solana"
    assert parse_gmgn_solana_mints(text) == [PUMP_MINT]


def test_parse_gmgn_alert_includes_author_when_present():
    text = f"GMGN New Token Alert\nCA: {PUMP_MINT}\nCreator: {AUTHOR}"
    alerts = parse_gmgn_solana_alerts(text)
    assert [(alert.mint, alert.author) for alert in alerts] == [(PUMP_MINT, AUTHOR)]


def test_parse_gmgn_alert_includes_liquidity_pool_when_present():
    lp_address = "7Hk3TnVKj8Jf5uVZLqGE2My5jX4QLkYywyTaJYo1cWcz"
    text = f"GMGN New Pool\nCA: {PUMP_MINT}\nLP: {lp_address}"
    alerts = parse_gmgn_solana_alerts(text)
    assert [(alert.mint, alert.liquidity_pool) for alert in alerts] == [
        (PUMP_MINT, lp_address)
    ]


def test_parse_gmgn_alert_leaves_author_blank_when_absent():
    alerts = parse_gmgn_solana_alerts(f"GMGN New Token Alert\nCA: {PUMP_MINT}")
    assert [(alert.mint, alert.author) for alert in alerts] == [(PUMP_MINT, "")]


def test_parse_open_age_min_supports_seconds_minutes_hours_days():
    assert parse_open_age_min("🕒 Open: 6s ago") == pytest.approx(0.1)
    assert parse_open_age_min("🕒 Open: 2min ago") == pytest.approx(2)
    assert parse_open_age_min("🕒 Open: 3h ago") == pytest.approx(180)
    assert parse_open_age_min("🕒 Open: 1d ago") == pytest.approx(1440)


def test_parse_filters_old_or_missing_open_age_when_limit_is_set():
    recent = f"GMGN New Token Alert\nCA: {PUMP_MINT}\n🕒 Open: 6s ago"
    old = f"GMGN New Token Alert\nCA: {PUMP_MINT}\n🕒 Open: 50d ago"
    missing = f"GMGN New Token Alert\nCA: {PUMP_MINT}"

    assert parse_gmgn_solana_mints(recent) == [PUMP_MINT]
    assert parse_gmgn_solana_alerts(recent, max_open_age_min=30)
    assert parse_gmgn_solana_alerts(old, max_open_age_min=30) == []
    assert parse_gmgn_solana_alerts(missing, max_open_age_min=30) == []


def test_launch_classifier_accepts_new_pool_and_rejects_lifecycle_alerts():
    assert is_gmgn_launch_alert(f"GMGN New Pool\nCA: {PUMP_MINT}")
    assert is_gmgn_launch_alert(f"Pump打满通知\nCA: {PUMP_MINT}")
    assert is_gmgn_launch_alert(f"💊 PUMP⚡6min 秒满\nCA: {PUMP_MINT}")
    assert is_gmgn_launch_alert(f"💊💊💊 PUMP已满 💊💊💊\nCA: {PUMP_MINT}")
    assert not is_gmgn_launch_alert(f"🔴PUMP DEV Sold🔴\nCA: {PUMP_MINT}")
    assert not is_gmgn_launch_alert(f"👑 Pump King of the hill (KOTH)\nCA: {PUMP_MINT}")


def test_parse_launch_only_rejects_dev_trade_alerts():
    dev_trade = f"🔴PUMP DEV Sold🔴\nCA: {PUMP_MINT}\nOpen: 6s ago"
    launch = f"GMGN New Pool\nCA: {PUMP_MINT}\nOpen: 6s ago"

    assert parse_gmgn_solana_alerts(dev_trade, max_open_age_min=30, launch_only=True) == []
    assert parse_gmgn_solana_alerts(launch, max_open_age_min=30, launch_only=True)


def test_parse_launch_only_accepts_new_pool_without_open_age():
    lp_address = "7Hk3TnVKj8Jf5uVZLqGE2My5jX4QLkYywyTaJYo1cWcz"
    text = f"CWSM 🏷️ NewPool新池子\n🎲 CA: {PUMP_MINT}\n💧 LP: {lp_address}"

    alerts = parse_gmgn_solana_alerts(text, max_open_age_min=30, launch_only=True)

    assert [(alert.mint, alert.liquidity_pool) for alert in alerts] == [
        (PUMP_MINT, lp_address)
    ]


def test_parse_launch_only_accepts_pump_filled_alert_without_lp():
    text = (
        "💊💊💊 PUMP已满 💊💊💊\n\n"
        "REEL (Reel Isles)\n\n"
        f"🎲 CA:\n{PUMP_MINT}\n\n"
        f"Check 立即研究 {PUMP_MINT}\n\n"
        "👥 Holder持有人: 84\n"
        "👑1/2 Process进度耗时: 31m 14s\n"
        "🚀2/2 Process进度耗时: 13m 2s\n"
    )

    alerts = parse_gmgn_solana_alerts(text, max_open_age_min=30, launch_only=True)

    assert [(alert.mint, alert.liquidity_pool) for alert in alerts] == [
        (PUMP_MINT, "")
    ]


def test_parse_gmgn_solana_urls_and_dedups():
    text = (
        f"https://gmgn.ai/sol/token/{BONK_MINT}\n"
        f"https://dexscreener.com/solana/{BONK_MINT}\n"
        f"mint: {PUMP_MINT}"
    )
    assert parse_gmgn_solana_mints(text) == [BONK_MINT, PUMP_MINT]


def test_parse_ignores_bsc_evm_contracts():
    text = (
        "BSC alert\n"
        "Contract: 0xb075f39b98d39634fb9612a4af2f87c3b2247777\n"
    )
    assert parse_gmgn_solana_mints(text) == []


def test_parse_empty_or_noise_returns_empty():
    assert parse_gmgn_solana_mints(None) == []
    assert parse_gmgn_solana_mints("price 0.00042 volume up") == []


def test_normalize_telegram_chat_ref_supports_usernames_and_numeric_ids():
    assert normalize_telegram_chat_ref("gmgn_sol_bot") == "gmgn_sol_bot"
    assert normalize_telegram_chat_ref("-1001234567890") == -1001234567890
    assert normalize_telegram_chat_ref(12345) == 12345


def test_normalize_telegram_chat_refs_supports_lists():
    assert normalize_telegram_chat_refs(["solnewlp", "-1001234567890"]) == [
        "solnewlp",
        -1001234567890,
    ]


class _FakeTelegramClient:
    def __init__(self, messages=None):
        self.handlers = []
        self.disconnected = asyncio.get_running_loop().create_future()
        self.started = False
        self.was_disconnected = False
        self.messages = list(messages or [])

    async def start(self):
        self.started = True

    def add_event_handler(self, handler, event_builder):
        self.handlers.append((handler, event_builder))

    def remove_event_handler(self, handler, event_builder):
        self.handlers.remove((handler, event_builder))

    async def disconnect(self):
        self.was_disconnected = True
        if not self.disconnected.done():
            self.disconnected.set_result(None)

    async def get_entity(self, chat):
        return chat

    async def iter_messages(self, entity, limit):
        for text in self.messages[:limit]:
            yield SimpleNamespace(raw_text=text)

    async def emit(self, text):
        event = SimpleNamespace(raw_text=text)
        for handler, _event_builder in list(self.handlers):
            await handler(event)


class _UnauthorizedTelegramClient:
    def __init__(self):
        self.disconnected = asyncio.get_running_loop().create_future()
        self.disconnected.set_result(None)
        self.disconnected_called = False

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return False

    async def disconnect(self):
        self.disconnected_called = True


class _FakeStore:
    def __init__(self):
        self.alerts = []
        self.events = []

    def save_discovery_alert(self, **kwargs):
        self.alerts.append(kwargs)

    def save_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


@pytest.mark.asyncio
async def test_feed_adds_mints_from_incoming_messages():
    buf = MintBuffer(ttl_sec=60)
    fake_client = _FakeTelegramClient()
    stop = asyncio.Event()

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        client_factory=lambda session, api_id, api_hash: fake_client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    task = asyncio.create_task(feed.run(stop))
    await asyncio.sleep(0)
    await fake_client.emit(f"GMGN New Token Alert\nCA: {PUMP_MINT}")
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert fake_client.started is True
    assert fake_client.was_disconnected is True
    assert feed.recent_mints() == [PUMP_MINT]


@pytest.mark.asyncio
async def test_feed_persists_mint_author_pairs_when_store_is_configured():
    buf = MintBuffer(ttl_sec=60)
    fake_client = _FakeTelegramClient()
    fake_store = _FakeStore()
    stop = asyncio.Event()

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        store=fake_store,
        client_factory=lambda session, api_id, api_hash: fake_client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    task = asyncio.create_task(feed.run(stop))
    await asyncio.sleep(0)
    await fake_client.emit(f"GMGN New Token Alert\nCA: {PUMP_MINT}\nAuthor: {AUTHOR}")
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert fake_store.alerts[0]["source"] == "gmgn_telegram"
    assert fake_store.alerts[0]["mint"] == PUMP_MINT
    assert fake_store.alerts[0]["author"] == AUTHOR
    assert fake_store.alerts[0]["liquidity_pool"] == ""
    assert fake_store.events[0][0] == ("gmgn",)
    assert fake_store.events[0][1]["mint"] == PUMP_MINT


@pytest.mark.asyncio
async def test_feed_rejects_old_alerts_when_open_age_limit_is_set():
    buf = MintBuffer(ttl_sec=60)
    fake_client = _FakeTelegramClient()
    fake_store = _FakeStore()
    stop = asyncio.Event()

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        store=fake_store,
        client_factory=lambda session, api_id, api_hash: fake_client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
        max_open_age_min=30,
    )

    task = asyncio.create_task(feed.run(stop))
    await asyncio.sleep(0)
    await fake_client.emit(f"GMGN New Token Alert\nCA: {PUMP_MINT}\nOpen: 50d ago")
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert fake_store.alerts == []
    assert buf.recent() == []


@pytest.mark.asyncio
async def test_feed_resolves_author_when_message_has_only_mint():
    buf = MintBuffer(ttl_sec=60)
    fake_client = _FakeTelegramClient()
    fake_store = _FakeStore()
    stop = asyncio.Event()

    async def _resolve_author(mint):
        assert mint == PUMP_MINT
        return AUTHOR

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        store=fake_store,
        author_resolver=_resolve_author,
        client_factory=lambda session, api_id, api_hash: fake_client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    task = asyncio.create_task(feed.run(stop))
    await asyncio.sleep(0)
    await fake_client.emit(f"GMGN New Token Alert\nCA: {PUMP_MINT}")
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert fake_store.alerts[0]["mint"] == PUMP_MINT
    assert fake_store.alerts[0]["author"] == AUTHOR
    assert fake_store.events[0][1]["detail"] == f"author={AUTHOR}"


@pytest.mark.asyncio
async def test_feed_backfills_recent_channel_messages():
    buf = MintBuffer(ttl_sec=60)
    fake_client = _FakeTelegramClient(messages=[f"GMGN New Pool\nCA: {BONK_MINT}"])
    fake_store = _FakeStore()

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat=["gmgnsignals", "solnewlp"],
        store=fake_store,
        client_factory=lambda session, api_id, api_hash: fake_client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
        backfill_limit=5,
    )

    stop = asyncio.Event()

    async def _stopper():
        while not fake_store.alerts:
            await asyncio.sleep(0.001)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(feed.run(stop), timeout=2.0)

    assert BONK_MINT in buf.recent()
    assert fake_store.alerts[0]["mint"] == BONK_MINT
    assert fake_store.events[0][1]["status"] == "backfill"


@pytest.mark.asyncio
async def test_feed_reconnects_after_client_error():
    buf = MintBuffer(ttl_sec=60)
    stop = asyncio.Event()
    fake_client = _FakeTelegramClient()
    calls = 0

    def _client_factory(session, api_id, api_hash):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("boom")
        return fake_client

    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        client_factory=_client_factory,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    async def _stopper():
        while not fake_client.handlers:
            await asyncio.sleep(0.001)
        await fake_client.emit(f"GMGN New Pool\nCA: {BONK_MINT}")
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(feed.run(stop), timeout=2.0)

    assert calls >= 2
    assert buf.recent() == [BONK_MINT]


@pytest.mark.asyncio
async def test_feed_raises_clear_error_when_session_is_not_authorized():
    buf = MintBuffer(ttl_sec=60)
    client = _UnauthorizedTelegramClient()
    feed = GMGNTelegramFeed(
        buf,
        api_id=12345,
        api_hash="hash",
        session="session",
        chat="gmgn_sol_bot",
        client_factory=lambda session, api_id, api_hash: client,
        new_message_factory=lambda **kwargs: kwargs,
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    with pytest.raises(RuntimeError, match="Telegram session is not authorized"):
        await feed._listen_once(asyncio.Event())
