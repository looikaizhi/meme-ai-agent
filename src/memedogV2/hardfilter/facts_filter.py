from __future__ import annotations

from memedogV2.hardfilter import rules as R
from memedogV2.sources.base import Facts


def evaluate_facts(f: Facts, cfg: dict) -> tuple[bool, list[str]]:
    """Run red-line rules over canonical Facts. Returns (passed, dropped_reasons).
    Degrades open on missing values (same policy as the gmgn-coupled filter)."""
    dropped: list[str] = []

    ok, reason = R.check_authorities(
        renounced_mint=f.mint_revoked, renounced_freeze=f.freeze_revoked,
        honeypot=(1 if f.honeypot else 0) if f.honeypot is not None else None)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_lp(
        burn_status=("burn" if f.lp_safe else "") if f.lp_safe is not None else None,
        lp_locked=f.lp_safe)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_concentration(top10_rate=f.top10_rate, creator_rate=f.creator_rate,
                                       dev_rate=f.dev_rate, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_manipulation(sniper_wallets=f.sniper_count, fresh_rate=f.fresh_wallet_rate,
                                      bundler_rate=f.bundler_rate, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    ratio = (f.buys_5m / f.sells_5m) if (f.buys_5m is not None and f.sells_5m) else None
    fdv = (f.price_usd * f.circulating_supply) if (f.price_usd is not None
                                                   and f.circulating_supply is not None) else None
    ok, reason = R.check_momentum(liquidity=f.liquidity_usd, volume_5m=f.volume_5m,
                                  buy_sell=ratio, fdv=fdv, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    return True, dropped
