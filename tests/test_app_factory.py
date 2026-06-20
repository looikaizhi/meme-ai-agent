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
