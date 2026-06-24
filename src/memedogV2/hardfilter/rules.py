from __future__ import annotations

from typing import Any, Optional


def get_path(obj: Any, dotted: str) -> Optional[Any]:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def num(v: Any) -> Optional[float]:
    """Coerce gmgn string/number to float; '' or None -> None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_authorities(*, renounced_mint: Optional[bool], renounced_freeze: Optional[bool],
                      honeypot: Optional[int]) -> tuple[bool, str]:
    if honeypot is not None and num(honeypot) == 1:
        return False, "authority: honeypot flagged"
    if renounced_mint is False:
        return False, "authority: mint not revoked"
    if renounced_freeze is False:
        return False, "authority: freeze not revoked"
    return True, "authorities ok (or unknown)"


def check_lp(*, burn_status: Optional[str], lp_locked: Optional[bool]) -> tuple[bool, str]:
    if burn_status is None and lp_locked is None:
        return True, "lp status unknown"
    if burn_status == "burn" or lp_locked is True:
        return True, "lp burned/locked"
    return False, "authority: LP not burned/locked"


def check_concentration(*, top10_rate: Any, creator_rate: Any, dev_rate: Any,
                        cfg: dict) -> tuple[bool, str]:
    v = num(top10_rate)
    if v is not None and v > cfg["max_top10_rate"]:
        return False, f"concentration: top10 {v} > {cfg['max_top10_rate']}"
    v = num(creator_rate)
    if v is not None and v > cfg["max_creator_rate"]:
        return False, f"concentration: creator {v} > {cfg['max_creator_rate']}"
    v = num(dev_rate)
    if v is not None and v > cfg["max_dev_rate"]:
        return False, f"concentration: dev {v} > {cfg['max_dev_rate']}"
    return True, "concentration ok (or unknown)"


def check_manipulation(*, sniper_wallets: Optional[int], fresh_rate: Any, bundler_rate: Any,
                       cfg: dict) -> tuple[bool, str]:
    if sniper_wallets is not None and sniper_wallets > cfg["max_sniper_wallets"]:
        return False, f"manipulation: snipers {sniper_wallets} > {cfg['max_sniper_wallets']}"
    v = num(fresh_rate)
    if v is not None and v > cfg["max_fresh_wallet_rate"]:
        return False, f"manipulation: fresh {v} > {cfg['max_fresh_wallet_rate']}"
    v = num(bundler_rate)
    if v is not None and v > cfg["max_bundler_rate"]:
        return False, f"manipulation: bundler {v} > {cfg['max_bundler_rate']}"
    return True, "manipulation ok (or unknown)"


def check_momentum(*, liquidity: Any, volume_5m: Any, buy_sell: Optional[float],
                   fdv: Optional[float], cfg: dict) -> tuple[bool, str]:
    liq = num(liquidity)
    if liq is not None and liq < cfg["min_liquidity_usd"]:
        return False, f"momentum: liquidity {liq} < {cfg['min_liquidity_usd']}"
    vol = num(volume_5m)
    if vol is not None and vol < cfg["min_volume_5m"]:
        return False, f"momentum: vol5m {vol} < {cfg['min_volume_5m']}"
    if buy_sell is not None and buy_sell < cfg["min_buy_sell_ratio_5m"]:
        return False, f"momentum: buy/sell {buy_sell} < {cfg['min_buy_sell_ratio_5m']}"
    if fdv is not None and liq and (fdv / liq) > cfg["max_fdv_to_liquidity"]:
        return False, f"momentum: fdv/liq {(fdv / liq):.1f} > {cfg['max_fdv_to_liquidity']}"
    return True, "momentum ok (or unknown)"
