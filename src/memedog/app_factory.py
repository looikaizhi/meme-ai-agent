"""Application factory for MemeDog Radar.

Wires all real module instances from a Config + Store, returning an Orchestrator
ready to run. No network calls are made at construction time — all clients are
built lazily (HTTP connections open only when the first request is made).

Public API:
  build_orchestrator(cfg, store) -> Orchestrator
  build_price_fn(dex_client)     -> async callable(mint: str) -> float | None
"""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.helius import HeliusClient
from memedog.clients.ratelimit import AsyncRateLimiter
from memedog.clients.rugcheck import RugCheckClient
from memedog.clients.twitter import TwitterClient
from memedog.config.settings import Config
from memedog.discovery.buffer import MintBuffer
from memedog.discovery.composite import CompositeFeed
from memedog.discovery.discoverer import MigrationDiscoverer
from memedog.discovery.helius_feed import HeliusMigrationFeed
from memedog.discovery.pumpportal import PumpPortalFeed
from memedog.enricher.enricher import Enricher
from memedog.hardfilter.hardfilter import HardFilter
from memedog.llmjudge.judge import LLMJudge
from memedog.orchestrator import Orchestrator
from memedog.papertrader.trader import PaperTrader
from memedog.scanner.scanner import Scanner
from memedog.scoring.engine import ScoreEngine
from memedog.store import Store

logger = logging.getLogger(__name__)


def build_discovery(cfg: Config, dex_client: DexScreenerClient | None = None):
    """Build the realtime discovery feed and Scanner adapter."""
    discovery = cfg.discovery
    buffer = MintBuffer(ttl_sec=discovery.buffer_ttl_min * 60)
    feeds = [
        PumpPortalFeed(
            buffer,
            url=discovery.pumpportal_ws_url,
            backoff_initial=discovery.reconnect_backoff_initial_sec,
            backoff_max=discovery.reconnect_backoff_max_sec,
        )
    ]

    if discovery.helius_enabled and cfg.settings.helius_api_key:
        helius_url = discovery.helius_ws_url.format(api_key=cfg.settings.helius_api_key)
        feeds.append(
            HeliusMigrationFeed(
                buffer,
                url=helius_url,
                program_id=discovery.pumpfun_program_id,
                backoff_initial=discovery.reconnect_backoff_initial_sec,
                backoff_max=discovery.reconnect_backoff_max_sec,
            )
        )

    feed = CompositeFeed(feeds, buffer=buffer)
    dex = dex_client if dex_client is not None else DexScreenerClient()
    discoverer = MigrationDiscoverer(feed=feed, dex_client=dex)
    return feed, discoverer


def build_orchestrator(cfg: Config, store: Store, demo: bool = False) -> Orchestrator:
    """Construct and wire all pipeline modules; return a ready Orchestrator.

    All HTTP clients are constructed without making any network calls —
    httpx opens connections lazily on first use.

    Parameters
    ----------
    cfg:
        Fully loaded :class:`~memedog.config.settings.Config`.
    store:
        Already-constructed :class:`~memedog.store.Store` instance.

    Returns
    -------
    Orchestrator
        Ready to run, with all collaborators wired.
    """
    # -----------------------------------------------------------------------
    # Demo mode: inject offline fixture-driven components (no network / codex)
    # -----------------------------------------------------------------------
    if demo:
        from memedog.demo.demo_source import (
            DemoScanner, DemoEnricher, DemoRugCheckClient, ReplayProvider,
        )
        return Orchestrator(
            scanner=DemoScanner(),
            hardfilter=HardFilter(rugcheck=DemoRugCheckClient(), cfg=cfg.hardfilter),
            enricher=DemoEnricher(),
            score_engine=ScoreEngine(cfg=cfg.scoring),
            llm_judge=LLMJudge(cfg.llmjudge, provider=ReplayProvider()),
            paper_trader=PaperTrader(store=store, cfg=cfg.papertrader),
            store=store,
            cfg=cfg,
        )

    # -----------------------------------------------------------------------
    # Data clients (each gets a per-source retry + rate-limit policy)
    # -----------------------------------------------------------------------
    def _http_kwargs(source: str) -> dict:
        pol = cfg.http.policy_for(source)
        return dict(
            timeout=pol.timeout_sec,
            max_retries=pol.max_retries,
            backoff_base=pol.backoff_base_sec,
            max_backoff=pol.max_backoff_sec,
            retry_status_codes=pol.retry_status_codes,
            rate_limiter=AsyncRateLimiter(pol.max_concurrency, pol.min_interval_sec),
        )

    dex_client = DexScreenerClient(**_http_kwargs("dexscreener"))
    feed, discoverer = build_discovery(cfg, dex_client=dex_client)

    rugcheck_client = RugCheckClient(**_http_kwargs("rugcheck"))

    helius_api_key: str = cfg.settings.helius_api_key or ""
    helius_client = HeliusClient(api_key=helius_api_key, **_http_kwargs("helius"))

    twitter_bearer: Optional[str] = cfg.settings.twitter_bearer
    twitter_client = TwitterClient(bearer_token=twitter_bearer, **_http_kwargs("twitter"))

    lunarcrush_client = None
    if cfg.enricher.lunarcrush_enabled and cfg.settings.lunarcrush_api_key:
        from memedog.clients.lunarcrush import LunarCrushClient
        lunarcrush_client = LunarCrushClient(
            api_key=cfg.settings.lunarcrush_api_key, **_http_kwargs("lunarcrush")
        )

    # -----------------------------------------------------------------------
    # Pipeline modules
    # -----------------------------------------------------------------------
    scanner = Scanner(client=discoverer, cfg=cfg.scanner)

    hardfilter = HardFilter(rugcheck=rugcheck_client, cfg=cfg.hardfilter)

    enricher = Enricher(
        rugcheck_client=rugcheck_client,
        helius_client=helius_client,
        twitter_client=twitter_client,
        cfg=cfg.enricher,
        lunarcrush_client=lunarcrush_client,
    )

    score_engine = ScoreEngine(cfg=cfg.scoring)

    llm_judge = LLMJudge(cfg=cfg.llmjudge)

    paper_trader = PaperTrader(store=store, cfg=cfg.papertrader)

    # -----------------------------------------------------------------------
    # Orchestrator
    # -----------------------------------------------------------------------
    return Orchestrator(
        scanner=scanner,
        hardfilter=hardfilter,
        enricher=enricher,
        score_engine=score_engine,
        llm_judge=llm_judge,
        paper_trader=paper_trader,
        store=store,
        cfg=cfg,
        feed=feed,
    )


def build_price_fn(dex_client: DexScreenerClient):
    """Build an async price function that queries DexScreener for a mint's price.

    The returned coroutine function is suitable for use with PriceWatcher.
    It returns the USD price (float) on success, or None on any failure.

    Parameters
    ----------
    dex_client:
        A :class:`~memedog.clients.dexscreener.DexScreenerClient` instance.

    Returns
    -------
    async callable(mint: str) -> float | None
    """

    async def price_fn(mint: str) -> Optional[float]:
        """Fetch the latest USD price for *mint* from DexScreener."""
        try:
            return await dex_client.get_token_price(mint)
        except Exception as exc:
            logger.warning("price_fn: error fetching price for mint=%s: %s", mint, exc)
            return None

    return price_fn
