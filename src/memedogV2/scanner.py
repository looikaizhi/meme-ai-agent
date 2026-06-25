from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from memedogV2.intake import AddressIntake

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_SOLANA_ADDRESS = rf"([{_BASE58_ALPHABET}]{{32,44}})"

_LABELED_CA_RE = re.compile(
    rf"(?i)\b(?:ca|mint|contract|contract\s+address|token\s+address)\s*[:：]\s*{_SOLANA_ADDRESS}"
)
_SOLANA_URL_RE = re.compile(
    rf"(?i)\b(?:solscan\.io/token|dexscreener\.com/solana|gmgn\.ai/sol/token|pump\.fun)"
    rf"/{_SOLANA_ADDRESS}"
)
_ANY_SOLANA_RE = re.compile(
    rf"(?<![{_BASE58_ALPHABET}]){_SOLANA_ADDRESS}(?![{_BASE58_ALPHABET}])"
)
_LP_RE = re.compile(
    rf"(?i)\b(?:lp|pool|pair|liquidity\s+pool)\s*(?:address)?\s*[:：]\s*{_SOLANA_ADDRESS}"
)
_OPEN_AGE_RE = re.compile(
    r"(?i)\bopen\s*[:：]\s*(\d+(?:\.\d+)?)\s*"
    r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)"
    r"\s+ago\b"
)
_EVM_RE = re.compile(r"(?i)\b0x[a-f0-9]{40}\b")

_LAUNCH_KEYWORDS = (
    "new pool",
    "new lp",
    "new pair",
    "new token",
    "new launch",
    "just launched",
    "launch",
    "pool created",
    "pair created",
    "liquidity added",
    "raydium launch",
    "pump filled",
    "pump token launched",
    "打满",
    "秒满",
    "已满",
    "新池",
    "新币",
    "新代币",
)
_NON_LAUNCH_KEYWORDS = (
    "dev sold",
    "dev bought",
    "king of the hill",
    "koth",
    "fdv surge",
    "burn alert",
    "lp burn",
)


class ScanItem(BaseModel):
    ca_address: str
    lp_address: str = ""
    source: str = "gmgn_telegram"
    raw_text: str = ""
    open_age_min: Optional[float] = None


class EnqueuedScanItem(BaseModel):
    item: ScanItem
    trace_id: str
    enqueued: bool


def parse_open_age_min(text: str | None) -> float | None:
    if not text:
        return None
    match = _OPEN_AGE_RE.search(text)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("s"):
        return value / 60.0
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return value
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return value * 60.0
    if unit in {"d", "day", "days"}:
        return value * 24.0 * 60.0
    return None


def is_launch_alert(text: str | None) -> bool:
    if not text:
        return False
    normalized = " ".join(text.lower().split())
    if any(keyword in normalized for keyword in _NON_LAUNCH_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in _LAUNCH_KEYWORDS)


def parse_launch_alerts(
    text: str | None,
    *,
    max_open_age_min: int | float | None = None,
    launch_only: bool = True,
    source: str = "gmgn_telegram",
) -> list[ScanItem]:
    """Extract every newly-launched Solana CA from one scanner alert.

    V2 intentionally does no market prefilter here. Every launch candidate gets
    queued; the downstream resolver, hardfilter, and LLM audit decide what dies.
    """
    if not text:
        return []
    if launch_only and not is_launch_alert(text):
        return []

    open_age_min = parse_open_age_min(text)
    if max_open_age_min is not None and open_age_min is not None:
        if open_age_min > max_open_age_min:
            return []

    evm_spans = [match.span() for match in _EVM_RE.finditer(text)]
    lp_matches = list(_LP_RE.finditer(text))
    lp_spans = [match.span(1) for match in lp_matches]
    lp_address = lp_matches[0].group(1) if lp_matches else ""

    def inside(spans: list[tuple[int, int]], start: int) -> bool:
        return any(span_start <= start < span_end for span_start, span_end in spans)

    candidates: list[tuple[int, str]] = []
    for regex in (_LABELED_CA_RE, _SOLANA_URL_RE, _ANY_SOLANA_RE):
        for match in regex.finditer(text):
            start = match.start(1)
            if inside(evm_spans, start) or inside(lp_spans, start):
                continue
            candidates.append((start, match.group(1)))

    seen: set[str] = set()
    items: list[ScanItem] = []
    for _start, ca in sorted(candidates, key=lambda item: item[0]):
        if ca in seen:
            continue
        seen.add(ca)
        items.append(
            ScanItem(
                ca_address=ca,
                lp_address="" if lp_address == ca else lp_address,
                source=source,
                raw_text=text,
                open_age_min=open_age_min,
            )
        )
    return items


class LaunchScanner:
    """Stateless launch scanner that feeds V2's AddressIntake queue."""

    def __init__(
        self,
        intake: AddressIntake,
        *,
        max_open_age_min: int | float | None = None,
        launch_only: bool = True,
        source: str = "gmgn_telegram",
    ) -> None:
        self._intake = intake
        self._max_open_age_min = max_open_age_min
        self._launch_only = launch_only
        self._source = source

    def scan_text(self, text: str | None) -> list[ScanItem]:
        return parse_launch_alerts(
            text,
            max_open_age_min=self._max_open_age_min,
            launch_only=self._launch_only,
            source=self._source,
        )

    def enqueue_text(self, text: str | None) -> list[EnqueuedScanItem]:
        results: list[EnqueuedScanItem] = []
        for item in self.scan_text(text):
            trace_id = self._intake.enqueue(item.ca_address, item.lp_address)
            results.append(
                EnqueuedScanItem(
                    item=item,
                    trace_id=trace_id,
                    enqueued=bool(trace_id),
                )
            )
        return results


class IntakeBufferAdapter:
    """Adapter for Telegram feed callbacks that expect a MintBuffer-like object."""

    def __init__(self, intake: AddressIntake, *, store=None) -> None:
        self._intake = intake
        self._store = store
        self._recent: list[str] = []

    def add(
        self,
        mint: str,
        *,
        source: str = "",
        author: str = "",
        liquidity_pool: str = "",
        raw_text: str = "",
    ) -> None:
        trace_id = self._intake.enqueue(mint, liquidity_pool)
        if trace_id:
            self._recent.append(mint)
            self._recent = self._recent[-100:]
        if self._store is not None:
            self._store.save_scanner_item(
                source=source or "gmgn_telegram",
                ca_address=mint,
                lp_address=liquidity_pool,
                trace_id=trace_id,
                enqueued=bool(trace_id),
                raw_text=raw_text,
            )

    def recent(self) -> list[str]:
        return list(self._recent)
