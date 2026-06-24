from __future__ import annotations

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.hardfilter import rules as R
from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.models.contracts import HardFilterResult


class HardFilter:
    """Deterministic gate. Calls gmgn-cli in cheapest-reject order: security -> info.

    Returns a HardFilterResult; never raises for rule failures. RateLimitBanned
    propagates to the caller. gmgn DataSourceError is handled via on_failure:
    'drop' (fail closed) or 'pass_flagged'.
    """

    def __init__(self, *, cli, cfg: dict, on_failure: str = "pass_flagged") -> None:
        if on_failure not in ("drop", "pass_flagged"):
            raise ValueError(f"on_failure must be 'drop' or 'pass_flagged', got {on_failure!r}")
        self._cli = cli
        self._cfg = cfg
        self._on_failure = on_failure

    def _val(self, facts: dict, key: str):
        return R.get_path(facts, FIELD_MAP[key])

    async def evaluate(self, ca: str, lp: str, trace_id: str = "") -> HardFilterResult:
        res = HardFilterResult(ca_address=ca, lp_address=lp, trace_id=trace_id)

        # --- Stage 1: security (authorities + LP) ---
        try:
            sec = await self._cli.token_security(ca)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            return self._on_source_error(res, "security", e)
        res.facts.update(sec)

        ok, reason = R.check_authorities(
            renounced_mint=self._val(res.facts, "renounced_mint"),
            renounced_freeze=self._val(res.facts, "renounced_freeze"),
            honeypot=self._val(res.facts, "honeypot"))
        if not ok:
            res.dropped.append(reason)
            return res

        ok, reason = R.check_lp(
            burn_status=self._val(res.facts, "burn_status"),
            lp_locked=self._val(res.facts, "lp_locked"))
        if not ok:
            res.dropped.append(reason)
            return res

        # --- Stage 2: info (concentration + manipulation + momentum) ---
        try:
            info = await self._cli.token_info(ca)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            return self._on_source_error(res, "info", e)
        res.facts.update(info)

        ok, reason = R.check_concentration(
            top10_rate=self._val(res.facts, "top10_rate"),
            creator_rate=self._val(res.facts, "creator_hold_rate"),
            dev_rate=self._val(res.facts, "dev_team_hold_rate"), cfg=self._cfg)
        if not ok:
            res.dropped.append(reason)
            return res

        ok, reason = R.check_manipulation(
            sniper_wallets=self._val(res.facts, "sniper_wallets"),
            fresh_rate=self._val(res.facts, "fresh_wallet_rate"),
            bundler_rate=self._val(res.facts, "bundler_rate"), cfg=self._cfg)
        if not ok:
            res.dropped.append(reason)
            return res

        buys = R.num(self._val(res.facts, "buys_5m"))
        sells = R.num(self._val(res.facts, "sells_5m"))
        ratio = (buys / sells) if (buys is not None and sells) else None
        price = R.num(self._val(res.facts, "price_usd"))
        supply = R.num(self._val(res.facts, "circulating_supply"))
        fdv = (price * supply) if (price is not None and supply is not None) else None
        ok, reason = R.check_momentum(
            liquidity=self._val(res.facts, "liquidity_usd"),
            volume_5m=self._val(res.facts, "volume_5m"),
            buy_sell=ratio, fdv=fdv, cfg=self._cfg)
        if not ok:
            res.dropped.append(reason)
            return res

        res.passed = True
        return res

    def _on_source_error(self, res: HardFilterResult, stage: str, exc: Exception) -> HardFilterResult:
        if self._on_failure == "drop":
            res.passed = False
            res.dropped.append(f"{stage}: source error ({exc})")
        else:  # pass_flagged
            res.passed = True
            res.flagged.append(f"{stage}: source error, passed flagged ({exc})")
        return res
