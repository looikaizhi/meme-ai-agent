from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Optional

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.clients.ratelimit import TokenBucket

Runner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


async def _subprocess_runner(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "gmgn-cli", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()


class GmgnCli:
    """Deterministic gmgn-cli wrapper: rate-limited, cached, 429-aware.

    NEVER retries on 429 — it raises RateLimitBanned so the caller can suspend
    until reset_at (retrying during cooldown extends the ban).
    """

    def __init__(
        self,
        *,
        runner: Optional[Runner] = None,
        chain: str = "sol",
        rate_per_sec: float = 1.0,
        capacity: int = 1,
        cache_ttl_sec: float = 60.0,
    ) -> None:
        self._runner = runner or _subprocess_runner
        self._chain = chain
        self._bucket = TokenBucket(rate_per_sec=rate_per_sec, capacity=capacity)
        self._ttl = cache_ttl_sec
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def token_security(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "security", ca)

    async def token_pool(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "pool", ca)

    async def token_info(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "info", ca)

    async def _run(self, group: str, sub: str, ca: str) -> dict[str, Any]:
        key = f"{group}:{sub}:{ca}"
        hit = self._cache.get(key)
        if hit and (time.time() - hit[0]) < self._ttl:
            return hit[1]

        await self._bucket.acquire()
        args = [group, sub, "--chain", self._chain, "--address", ca, "--raw"]
        code, stdout, stderr = await self._runner(args)

        parsed = self._try_parse(stdout)
        if parsed is not None and self._is_429(parsed):
            raise RateLimitBanned(str(parsed), reset_at=parsed.get("reset_at"))
        if code != 0:
            raise DataSourceError(f"gmgn-cli {group} {sub} rc={code}: {stderr.strip()}")
        if parsed is None:
            raise DataSourceError(f"gmgn-cli {group} {sub}: unparseable output")

        self._cache[key] = (time.time(), parsed)
        return parsed

    @staticmethod
    def _try_parse(s: str) -> Optional[dict[str, Any]]:
        s = s.strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {"_list": obj}
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _is_429(obj: dict[str, Any]) -> bool:
        return obj.get("code") == 429 or str(obj.get("error", "")).startswith("RATE_LIMIT")
