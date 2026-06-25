from __future__ import annotations

import json
import time
from typing import Any, Protocol

from memedogV2.harness.contracts import ToolCallRecord


class ToolSource(Protocol):
    async def security(self, ca: str) -> dict[str, Any]: ...
    async def info(self, ca: str) -> dict[str, Any]: ...


class FixtureToolSource:
    """Returns canned dicts; no network. For unit tests."""

    def __init__(self, *, security: dict, info: dict) -> None:
        self._security = security
        self._info = info

    async def security(self, ca: str) -> dict[str, Any]:
        return self._security

    async def info(self, ca: str) -> dict[str, Any]:
        return self._info


class GmgnCliToolSource:
    """Wraps the real rate-limited GmgnCli."""

    def __init__(self, cli) -> None:
        self._cli = cli

    async def security(self, ca: str) -> dict[str, Any]:
        return await self._cli.token_security(ca)

    async def info(self, ca: str) -> dict[str, Any]:
        return await self._cli.token_info(ca)


class ToolRegistry:
    """Fetches gmgn data through a ToolSource and records each call."""

    def __init__(self, *, source: ToolSource) -> None:
        self._source = source

    async def _fetch(self, sub: str, ca: str, coro) -> tuple[dict, ToolCallRecord]:
        t0 = time.perf_counter()
        data = await coro
        dur = (time.perf_counter() - t0) * 1000.0
        rec = ToolCallRecord(
            tool="gmgn-cli",
            command=f"token {sub} {ca}",
            input_summary=ca,
            output_summary=(json.dumps(data)[:200] if isinstance(data, dict) else str(data)[:200]),
            exit_status=0,
            duration_ms=dur,
        )
        return data, rec

    async def fetch_security(self, ca: str) -> tuple[dict, ToolCallRecord]:
        return await self._fetch("security", ca, self._source.security(ca))

    async def fetch_info(self, ca: str) -> tuple[dict, ToolCallRecord]:
        return await self._fetch("info", ca, self._source.info(ca))
