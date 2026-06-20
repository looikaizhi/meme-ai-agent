"""Tests for CodexCLIProvider (Task 2). Never spawns a real codex process."""
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memedog.llm.provider import LLMProviderError
from memedog.llm.codex_provider import CodexCLIProvider


def _make_fake_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    """Return a mock process whose communicate() returns (stdout, stderr)."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_provider_success_path(monkeypatch, tmp_path):
    """Provider reads from --output-last-message file and returns stripped text."""
    expected_text = "BULLISH analysis here"

    async def fake_subprocess(*cmd, **kwargs):
        # Find the --output-last-message file path in the command
        cmd_list = list(cmd)
        idx = cmd_list.index("--output-last-message")
        out_file = cmd_list[idx + 1]
        # Write the expected output to that file
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"  {expected_text}  \n")
        return _make_fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    provider = CodexCLIProvider()
    result = await provider.complete(
        model="gpt-4o",
        messages=[{"role": "user", "content": "analyze this token"}],
    )
    assert result == expected_text


@pytest.mark.asyncio
async def test_codex_provider_model_flag_included_when_set(monkeypatch):
    """When model is truthy, --model <m> flag should appear in command."""
    captured_cmd = []

    async def fake_subprocess(*cmd, **kwargs):
        captured_cmd.extend(cmd)
        # Write output file
        idx = list(cmd).index("--output-last-message")
        out_file = list(cmd)[idx + 1]
        with open(out_file, "w") as f:
            f.write("ok")
        return _make_fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = CodexCLIProvider()
    await provider.complete(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    assert "--model" in captured_cmd
    idx = captured_cmd.index("--model")
    assert captured_cmd[idx + 1] == "gpt-4o"


@pytest.mark.asyncio
async def test_codex_provider_no_model_flag_when_empty(monkeypatch):
    """When model is empty string, --model should NOT appear in command."""
    captured_cmd = []

    async def fake_subprocess(*cmd, **kwargs):
        captured_cmd.extend(cmd)
        idx = list(cmd).index("--output-last-message")
        out_file = list(cmd)[idx + 1]
        with open(out_file, "w") as f:
            f.write("ok")
        return _make_fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = CodexCLIProvider()
    await provider.complete(model="", messages=[{"role": "user", "content": "hi"}])

    assert "--model" not in captured_cmd


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_provider_nonzero_exit_raises(monkeypatch):
    """Non-zero returncode → LLMProviderError."""

    async def fake_subprocess(*cmd, **kwargs):
        idx = list(cmd).index("--output-last-message")
        out_file = list(cmd)[idx + 1]
        # Don't write the file — exit non-zero
        return _make_fake_proc(returncode=1, stderr=b"codex error message")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = CodexCLIProvider()
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete(model="", messages=[{"role": "user", "content": "hi"}])
    assert "codex error message" in str(exc_info.value)


@pytest.mark.asyncio
async def test_codex_provider_timeout_raises(monkeypatch):
    """Timeout → LLMProviderError; process gets killed."""

    killed = []

    async def fake_communicate():
        await asyncio.sleep(9999)

    async def fake_subprocess(*cmd, **kwargs):
        proc = MagicMock()
        proc.returncode = None
        proc.communicate = fake_communicate
        proc.kill = lambda: killed.append(True)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = CodexCLIProvider(timeout=0.01)  # very short timeout
    with pytest.raises(LLMProviderError):
        await provider.complete(model="", messages=[{"role": "user", "content": "hi"}])
    assert killed, "Process should have been killed on timeout"


# ---------------------------------------------------------------------------
# Command structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_provider_command_structure(monkeypatch):
    """Verify the command contains required codex flags."""
    captured_cmd = []

    async def fake_subprocess(*cmd, **kwargs):
        captured_cmd.extend(cmd)
        idx = list(cmd).index("--output-last-message")
        out_file = list(cmd)[idx + 1]
        with open(out_file, "w") as f:
            f.write("result")
        return _make_fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = CodexCLIProvider(codex_bin="mycodex", sandbox="read-only")
    await provider.complete(model="", messages=[{"role": "user", "content": "test prompt"}])

    assert captured_cmd[0] == "mycodex"
    assert "exec" in captured_cmd
    assert "--sandbox" in captured_cmd
    idx = captured_cmd.index("--sandbox")
    assert captured_cmd[idx + 1] == "read-only"
    assert "--ask-for-approval" in captured_cmd
    assert "--skip-git-repo-check" in captured_cmd
    assert "--output-last-message" in captured_cmd
