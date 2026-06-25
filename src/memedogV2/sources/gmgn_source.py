from __future__ import annotations

import asyncio
import time

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.hardfilter.rules import get_path, num
from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import PartialFacts


def _b(v):
    return bool(v) if isinstance(v, bool) else (None if v is None else bool(v))


class GmgnSource:
    """gmgn-cli source: security+info -> normalized PartialFacts. Bounded retry on
    transient (non-429) errors; 429 propagates as RateLimitBanned (never retried)."""
    name = "gmgn"

    def __init__(self, *, cli, max_retries: int = 2) -> None:
        self._cli = cli
        self._max_retries = max_retries

    async def fetch(self, ca: str, lp: str) -> tuple[PartialFacts, ToolCallRecord]:
        t0 = time.perf_counter()
        try:
            facts = await self._fetch_with_retry(ca)
            dur = (time.perf_counter() - t0) * 1000.0
            return facts, ToolCallRecord(tool="gmgn", command=f"token security+info {ca}",
                                         input_summary=ca, exit_status=0, duration_ms=dur)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="gmgn", command=f"token security+info {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)

    async def _fetch_with_retry(self, ca: str):
        sec = await self._cli.token_security(ca)
        attempt = 0
        while True:
            try:
                info = await self._cli.token_info(ca)
                break
            except RateLimitBanned:
                raise
            except DataSourceError:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                await asyncio.sleep(min(2.0, 0.2 * (2 ** attempt)))
        return self._normalize(sec, info)

    @staticmethod
    def _normalize(sec: dict, info: dict) -> PartialFacts:
        facts = {**sec, **info}

        def f(key):
            return num(get_path(facts, FIELD_MAP[key]))

        burn = get_path(facts, FIELD_MAP["burn_status"])
        locked = get_path(facts, FIELD_MAP["lp_locked"])
        lp_safe = None
        if burn is not None or locked is not None:
            lp_safe = (burn == "burn") or (locked is True)
        honeypot_v = f("honeypot")

        def as_int(key):
            v = f(key)
            return int(v) if v is not None else None

        return PartialFacts(
            mint_revoked=_b(get_path(facts, FIELD_MAP["renounced_mint"])),
            freeze_revoked=_b(get_path(facts, FIELD_MAP["renounced_freeze"])),
            lp_safe=lp_safe,
            honeypot=(honeypot_v == 1) if honeypot_v is not None else None,
            top10_rate=f("top10_rate"), max_wallet_rate=None,
            creator_rate=f("creator_hold_rate"), dev_rate=f("dev_team_hold_rate"),
            sniper_count=as_int("sniper_wallets"),
            fresh_wallet_rate=f("fresh_wallet_rate"), bundler_rate=f("bundler_rate"),
            liquidity_usd=f("liquidity_usd"), volume_5m=f("volume_5m"),
            buys_5m=as_int("buys_5m"), sells_5m=as_int("sells_5m"),
            price_usd=f("price_usd"), circulating_supply=f("circulating_supply"),
            smart_money_count=as_int("smart_wallets"), kol_count=as_int("renowned_wallets"),
            dev_created_count=as_int("dev_created_count"), historical_ath=f("dev_ath_mc"),
        )
