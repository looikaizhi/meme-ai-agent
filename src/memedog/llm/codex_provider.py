"""CodexCLIProvider — runs the Codex CLI as a subprocess.

The Codex CLI is invoked as::

    codex exec --sandbox read-only --skip-git-repo-check
               --output-last-message <tmpfile>
               [--model <model>]  # omitted when model is empty
               "<flattened prompt>"

``temperature`` and ``max_tokens`` are accepted but unused — the Codex CLI
has no direct CLI flags for these parameters.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from asyncio.subprocess import PIPE

from memedog.llm.provider import LLMMessage, LLMProviderError

log = logging.getLogger(__name__)


class CodexCLIProvider:
    """Wraps the Codex CLI binary as an async subprocess provider."""

    def __init__(
        self,
        codex_bin: str = "codex",
        timeout: float = 120,
        sandbox: str = "read-only",
    ) -> None:
        self._bin = codex_bin
        self._timeout = timeout
        self._sandbox = sandbox

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten(messages: list[LLMMessage]) -> str:
        """Concatenate role+content pairs into a single prompt string."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        temperature: float = 0.3,  # accepted but unused — Codex CLI has no flag
        max_tokens: int = 1024,   # accepted but unused — Codex CLI has no flag
    ) -> str:
        prompt = self._flatten(messages)

        # Create a temp file for --output-last-message
        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="memedog_codex_")
        os.close(fd)

        cmd: list[str] = [
            self._bin,
            "exec",
            "--sandbox", self._sandbox,
            "--skip-git-repo-check",
            "--output-last-message", tmp_path,
        ]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=PIPE,
                stderr=PIPE,
            )
            try:
                _stdout, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                raise LLMProviderError(
                    f"Codex CLI timed out after {self._timeout}s"
                )

            if proc.returncode != 0:
                snippet = (stderr_bytes or b"").decode("utf-8", errors="replace")[:500]
                raise LLMProviderError(
                    f"Codex CLI exited with code {proc.returncode}: {snippet}"
                )

            with open(tmp_path, "r", encoding="utf-8") as fh:
                return fh.read().strip()

        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
