"""Tests for app_factory — Task 2.

Verifies that:
- build_orchestrator(cfg, store) returns an Orchestrator without making network calls.
- The returned orchestrator has all expected collaborators wired (attributes not None).
- Importing memedog.__main__ does NOT call asyncio.run() (no side effects at import).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memedog.config.settings import load_config
from memedog.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "factory_test.db")


@pytest.fixture
def store(db_path: str) -> Store:
    s = Store(db_path)
    yield s
    s.close()


@pytest.fixture
def cfg():
    return load_config()


# ---------------------------------------------------------------------------
# Test: build_orchestrator returns Orchestrator with wired collaborators
# ---------------------------------------------------------------------------


def test_build_orchestrator_returns_orchestrator(cfg, store):
    """build_orchestrator should return an Orchestrator with all collaborators set."""
    from memedog.app_factory import build_orchestrator
    from memedog.orchestrator import Orchestrator

    orch = build_orchestrator(cfg, store)

    assert isinstance(orch, Orchestrator)

    # Every internal collaborator must be set (not None)
    assert orch._scanner is not None
    assert orch._hardfilter is not None
    assert orch._enricher is not None
    assert orch._score_engine is not None
    assert orch._llm_judge is not None
    assert orch._paper_trader is not None
    assert orch._store is not None
    assert orch._cfg is not None


def test_build_orchestrator_no_network_calls(cfg, store, monkeypatch):
    """Constructing the orchestrator must not make any real HTTP requests.

    httpx.AsyncClient is instantiated eagerly in BaseHTTPClient (that's fine —
    object creation is not a network call).  We verify no actual HTTP requests
    are dispatched by patching the AsyncClient.request method to raise.
    """
    import httpx

    original_init = httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Patch the request method on each new instance so any HTTP call raises
        async def _raise_on_request(method, url, **kw):
            raise AssertionError(
                f"HTTP request made during orchestrator construction: {method} {url}"
            )
        self.request = _raise_on_request  # type: ignore[method-assign]

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)

    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store)
    assert orch is not None


def test_build_orchestrator_store_is_passed(cfg, store):
    """The store passed in should be wired into the returned orchestrator."""
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store)
    assert orch._store is store


def test_build_orchestrator_cfg_is_passed(cfg, store):
    """The cfg passed in should be wired into the returned orchestrator."""
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store)
    assert orch._cfg is cfg


# ---------------------------------------------------------------------------
# Test: build_price_fn returns a callable
# ---------------------------------------------------------------------------


def test_build_price_fn_returns_callable(cfg):
    """build_price_fn should return an async callable (coroutine function)."""
    import asyncio
    from memedog.app_factory import build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient

    dex_client = DexScreenerClient()
    price_fn = build_price_fn(dex_client)

    # Should be a coroutine function (async def)
    assert asyncio.iscoroutinefunction(price_fn)


@pytest.mark.asyncio
async def test_build_price_fn_delegates_to_get_token_price(cfg):
    """build_price_fn delegates to get_token_price and returns the float price."""
    from unittest.mock import AsyncMock
    from memedog.app_factory import build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient

    dex_client = DexScreenerClient()
    dex_client.get_token_price = AsyncMock(return_value=1.23)

    price_fn = build_price_fn(dex_client)
    result = await price_fn("SOMEMINT")

    assert result == pytest.approx(1.23)
    dex_client.get_token_price.assert_awaited_once_with("SOMEMINT")


@pytest.mark.asyncio
async def test_build_price_fn_returns_none_on_exception(cfg):
    """build_price_fn catches exceptions from get_token_price and returns None."""
    from unittest.mock import AsyncMock
    from memedog.app_factory import build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient
    from memedog.clients.base import DataSourceError

    dex_client = DexScreenerClient()
    dex_client.get_token_price = AsyncMock(side_effect=DataSourceError("network failure"))

    price_fn = build_price_fn(dex_client)
    result = await price_fn("SOMEMINT")

    assert result is None


# ---------------------------------------------------------------------------
# Test: __main__ imports without side effects
# ---------------------------------------------------------------------------


def test_main_imports_without_side_effects():
    """Importing memedog.__main__ must not trigger asyncio.run() or any I/O."""
    # If this import itself blocks, pytest will hang; we just verify it completes
    import importlib
    import sys

    # Remove cached module if already imported
    sys.modules.pop("memedog.__main__", None)

    # Import — should complete without hanging
    mod = importlib.import_module("memedog.__main__")

    # The module should have a 'main' async function
    assert hasattr(mod, "main")
    import asyncio
    assert asyncio.iscoroutinefunction(mod.main)


# ---------------------------------------------------------------------------
# Test: http policy + rate limiter wiring (sub-project B)
# ---------------------------------------------------------------------------


def test_clients_get_rate_limiter_and_policy(cfg, store):
    from memedog.app_factory import build_orchestrator
    from memedog.clients.ratelimit import AsyncRateLimiter

    orch = build_orchestrator(cfg, store)
    # scanner's client is the migration adapter; pair enrichment still uses DexScreener
    scanner_client = orch._scanner._client._dex
    assert isinstance(scanner_client._rate_limiter, AsyncRateLimiter)
    # dexscreener override leaves timeout at default → matches policy_for
    assert scanner_client._timeout == cfg.http.policy_for("dexscreener").timeout_sec


def test_build_orchestrator_demo_injects_demo_components(cfg, store):
    from memedog.app_factory import build_orchestrator
    from memedog.demo.demo_source import DemoScanner, DemoEnricher, ReplayProvider

    orch = build_orchestrator(cfg, store, demo=True)
    assert isinstance(orch._scanner, DemoScanner)
    assert isinstance(orch._enricher, DemoEnricher)
    assert isinstance(orch._llm_judge._injected_provider, ReplayProvider)


@pytest.mark.asyncio
async def test_build_orchestrator_demo_cycle_runs_offline(cfg, store):
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store, demo=True)
    signals = await orch.run_cycle()
    assert len(signals) >= 1
    stages = [e["stage"] for e in store.recent_events(limit=50)]
    assert "judge" in stages and "signal" in stages


def test_build_discovery_returns_feed_and_discoverer(cfg):
    from memedog.app_factory import build_discovery
    from memedog.discovery.discoverer import MigrationDiscoverer

    feed, discoverer = build_discovery(cfg)
    assert isinstance(discoverer, MigrationDiscoverer)
    assert hasattr(feed, "run") and hasattr(feed, "recent_mints")


def test_build_discovery_adds_gmgn_feed_when_enabled(cfg):
    from memedog.app_factory import build_discovery
    from memedog.discovery.gmgn_telegram import GMGNTelegramFeed

    cfg2 = cfg.model_copy(
        update={
            "discovery": cfg.discovery.model_copy(update={"gmgn_enabled": True}),
            "settings": cfg.settings.model_copy(
                update={
                    "telegram_api_id": 12345,
                    "telegram_api_hash": "telegram-api-hash",
                    "telegram_session": "test-session",
                }
            ),
        }
    )

    feed, _discoverer = build_discovery(cfg2)

    assert any(isinstance(subfeed, GMGNTelegramFeed) for subfeed in feed._feeds)


def test_build_discovery_skips_gmgn_without_user_client_credentials(cfg):
    from memedog.app_factory import build_discovery
    from memedog.discovery.gmgn_telegram import GMGNTelegramFeed

    cfg2 = cfg.model_copy(
        update={
            "discovery": cfg.discovery.model_copy(update={"gmgn_enabled": True}),
            "settings": cfg.settings.model_copy(
                update={"telegram_api_id": None, "telegram_api_hash": None}
            ),
        }
    )

    feed, _discoverer = build_discovery(cfg2)

    assert not any(isinstance(subfeed, GMGNTelegramFeed) for subfeed in feed._feeds)


def test_production_orchestrator_exposes_feed(cfg, store):
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store, demo=False)
    assert orch.feed is not None
    assert hasattr(orch.feed, "run")


def test_demo_orchestrator_has_no_feed(cfg, store):
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store, demo=True)
    assert orch.feed is None
