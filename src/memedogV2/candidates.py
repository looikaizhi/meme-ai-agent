from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional

from memedogV2.clients.errors import DataSourceError

MarketKind = Literal["trending", "signal", "trenches"]
Runner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


@dataclass(frozen=True)
class MarketCandidate:
    ca_address: str
    lp_address: str = ""
    source: str = "gmgn_market"
    stage: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


async def _subprocess_runner(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "gmgn-cli",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()


async def fetch_gmgn_market_candidates(
    kind: MarketKind,
    *,
    chain: str = "sol",
    limit: int = 10,
    interval: str = "5m",
    order_by: str | None = None,
    direction: str | None = None,
    filters: list[str] | None = None,
    platforms: list[str] | None = None,
    signal_types: list[int] | None = None,
    trenches_types: list[str] | None = None,
    filter_preset: str | None = None,
    sort_by: str | None = None,
    runner: Optional[Runner] = None,
) -> list[MarketCandidate]:
    """Fetch and normalize candidates from GMGN market discovery commands."""
    args = ["market", kind, "--chain", chain]
    if kind == "trending":
        args += ["--interval", interval, "--limit", str(limit)]
        if order_by:
            args += ["--order-by", order_by]
        if direction:
            args += ["--direction", direction]
        for value in filters or []:
            args += ["--filter", value]
        for value in platforms or []:
            args += ["--platform", value]
    elif kind == "signal":
        for value in signal_types or []:
            args += ["--signal-type", str(value)]
    elif kind == "trenches":
        args += ["--limit", str(limit)]
        for value in trenches_types or []:
            args += ["--type", value]
        if filter_preset:
            args += ["--filter-preset", filter_preset]
        if sort_by:
            args += ["--sort-by", sort_by]
        if direction:
            args += ["--direction", direction]
    else:  # pragma: no cover - kept for defensive runtime callers.
        raise ValueError(f"unsupported GMGN market kind: {kind}")

    args.append("--raw")
    run = runner or _subprocess_runner
    code, stdout, stderr = await run(args)
    if code != 0:
        detail = stderr.strip() or stdout.strip()
        raise DataSourceError(f"gmgn-cli {' '.join(args)} rc={code}: {detail}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DataSourceError("gmgn-cli market output was not valid JSON") from exc

    return extract_market_candidates(
        payload,
        source=f"gmgn_{kind}",
        stage=kind,
        limit=limit,
    )


def extract_market_candidates(
    payload: Any,
    *,
    source: str = "gmgn_market",
    stage: str = "unknown",
    limit: int | None = None,
) -> list[MarketCandidate]:
    """Normalize GMGN market/trenches/signal response shapes into addresses."""
    items = _iter_items(payload)
    seen: set[str] = set()
    out: list[MarketCandidate] = []
    for item in items:
        ca = _first_str(item, "token_address", "address")
        nested = item.get("data") if isinstance(item.get("data"), dict) else {}
        if not ca:
            ca = _first_str(nested, "token_address", "address")
        if not ca or ca in seen:
            continue

        lp = _first_str(item, "pool_address", "pair_address")
        if not lp:
            lp = _first_str(nested, "pool_address", "pair_address")
        seen.add(ca)
        item_stage = str(item.get("_stage") or stage or "unknown")
        out.append(
            MarketCandidate(
                ca_address=ca,
                lp_address=lp,
                source=source,
                stage=item_stage,
                raw=item,
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def _iter_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("rank"), list):
        return [item for item in data["rank"] if isinstance(item, dict)]

    out: list[dict[str, Any]] = []
    for key in ("new_creation", "near_completion", "completed", "pump"):
        values = payload.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    out.append({**item, "_stage": key})
    return out


def _first_str(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
