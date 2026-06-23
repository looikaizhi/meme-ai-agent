"""Helius logsSubscribe redundancy feed for pump.fun migrations."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from memedog.discovery.buffer import MintBuffer

logger = logging.getLogger(__name__)


def _logs_of(msg: dict) -> list[str]:
    try:
        return msg["params"]["result"]["value"]["logs"] or []
    except (KeyError, TypeError):
        return []


def parse_helius_log(msg: Any) -> str | None:
    """Conservatively extract a migrated mint from a Helius log notification."""
    if not isinstance(msg, dict):
        return None
    logs = _logs_of(msg)
    if not logs:
        return None
    is_migration = any(
        ("migrate" in line.lower())
        or ("Withdraw" in line)
        or ("Instruction: Create" in line)
        for line in logs
    )
    if not is_migration:
        return None

    try:
        account_keys = msg["params"]["result"]["value"].get("accountKeys")
    except (KeyError, TypeError):
        account_keys = None
    if isinstance(account_keys, list):
        for account in account_keys:
            if isinstance(account, str) and account.endswith("pump"):
                if 32 <= len(account) <= 44:
                    return account
    return None


class HeliusMigrationFeed:
    """Reliability backup feed via Helius logsSubscribe."""

    def __init__(
        self,
        buffer: MintBuffer,
        *,
        url: str,
        program_id: str,
        connect=None,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._buffer = buffer
        self._url = url
        self._program_id = program_id
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        if connect is None:
            import websockets

            connect = websockets.connect
        self._connect = connect

    def recent_mints(self) -> list[str]:
        return self._buffer.recent()

    def _subscribe_payload(self) -> str:
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [self._program_id]},
                    {"commitment": "processed"},
                ],
            }
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = self._backoff_initial
        while not stop_event.is_set():
            try:
                async with self._connect(self._url) as ws:
                    await ws.send(self._subscribe_payload())
                    backoff = self._backoff_initial
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        mint = parse_helius_log(msg)
                        if mint:
                            self._buffer.add(mint)
            except Exception as exc:
                logger.warning("HeliusMigrationFeed connection error: %s", exc)
            if stop_event.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)
