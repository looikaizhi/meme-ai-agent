from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Awaitable, Callable, Optional

Executor = Callable[..., Awaitable[str]]


async def _codex_exec(*, prompt: str, schema: dict, cwd: str) -> str:
    """Run `codex exec` with network + structured output; return last message text.

    Uses the invocation confirmed in the Phase 0 spike:
    - --dangerously-bypass-approvals-and-sandbox  (gmgn-cli needs network)
    - --output-schema <strict schema>             (structured output)
    - stdin closed via DEVNULL                     (else codex hangs reading stdin)
    """
    schema_fd, schema_path = tempfile.mkstemp(suffix=".json", prefix="v2_schema_")
    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="v2_out_")
    os.close(schema_fd)
    os.close(out_fd)
    try:
        with open(schema_path, "w") as f:
            json.dump(schema, f)
        args = [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--output-schema", schema_path,
            "-o", out_path,
            prompt,
        ]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"codex exec rc={proc.returncode}: {err.decode().strip()}")
        with open(out_path) as f:
            return f.read()
    finally:
        for p in (schema_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


class CodexAgent:
    """Thin wrapper: prompt + strict JSON schema -> parsed dict via `codex exec`."""

    def __init__(self, *, executor: Optional[Executor] = None, cwd: str = ".") -> None:
        self._exec = executor or _codex_exec
        self._cwd = cwd

    async def run(self, *, prompt: str, schema: dict) -> dict[str, Any]:
        raw = await self._exec(prompt=prompt, schema=schema, cwd=self._cwd)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"codex output not valid JSON: {raw[:200]}") from e
