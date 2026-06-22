"""Application factory for MemeDog Radar.

Wires all real module instances from a Config + Store, returning an Orchestrator
ready to run. No network calls are made at construction time — all clients are
built lazily (HTTP connections open only when the first request is made).

Public API:
  build_orchestrator(cfg, store) -> Orchestrator
  build_market_data_client(cfg)  -> configured scanner / price data client
  build_price_fn(market_client)  -> async callable(mint: str) -> float | None
"""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.bitget_mcp import BitgetMCPMarketDataClient
from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.helius import HeliusClient
from memedog.clients.rugcheck import RugCheckClient
from memedog.clients.twitter import TwitterClient
from memedog.config.settings import Config
from memedog.enricher.enricher import Enricher
from memedog.hardfilter.hardfilter import HardFilter
from memedog.llmjudge.judge import LLMJudge
from memedog.orchestrator import Orchestrator
from memedog.papertrader.trader import PaperTrader
from memedog.scanner.scanner import Scanner
from memedog.scoring.engine import ScoreEngine
from memedog.store import Store

logger = logging.getLogger(__name__)


def build_market_data_client(cfg: Config):
    """Build the configured market-data client for scanner and price polling."""
    if cfg.scanner.source == "bitget_mcp":
        return BitgetMCPMarketDataClient(url=cfg.scanner.bitget_mcp_url)
    return DexScreenerClient()


def build_orchestrator(cfg: Config, store: Store) -> Orchestrator:
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
    # Data clients
    # -----------------------------------------------------------------------
    scanner_client = build_market_data_client(cfg)

    rugcheck_client = RugCheckClient()

    helius_api_key: str = cfg.settings.helius_api_key or ""
    helius_client = HeliusClient(api_key=helius_api_key)

    twitter_bearer: Optional[str] = cfg.settings.twitter_bearer
    twitter_client = TwitterClient(bearer_token=twitter_bearer)

    # -----------------------------------------------------------------------
    # Pipeline modules
    # -----------------------------------------------------------------------
    scanner = Scanner(client=scanner_client, cfg=cfg.scanner)

    hardfilter = HardFilter(rugcheck=rugcheck_client, cfg=cfg.hardfilter)

    enricher = Enricher(
        rugcheck_client=rugcheck_client,
        helius_client=helius_client,
        twitter_client=twitter_client,
        cfg=cfg.enricher,
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
    )


def build_price_fn(market_client):
    """Build an async price function that queries the configured market-data source.

    The returned coroutine function is suitable for use with PriceWatcher.
    It returns the USD price (float) on success, or None on any failure.

    Parameters
    ----------
    market_client:
        Any client exposing ``get_token_price(mint)``.

    Returns
    -------
    async callable(mint: str) -> float | None
    """

    async def price_fn(mint: str) -> Optional[float]:
        """Fetch the latest USD price for *mint*."""
        try:
            return await market_client.get_token_price(mint)
        except Exception as exc:
            logger.warning("price_fn: error fetching price for mint=%s: %s", mint, exc)
            return None

    return price_fn
