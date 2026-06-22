"""Tests for the serve launcher (no real streamlit / network)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from memedog import serve


def test_build_streamlit_cmd_includes_port_and_app():
    cmd = serve.build_streamlit_cmd(port=8599, dashboard_path="dashboard/app.py")
    assert "streamlit" in cmd
    assert "run" in cmd
    assert "dashboard/app.py" in cmd
    assert "8599" in cmd


def test_parse_args_demo_and_port():
    args = serve.parse_args(["--demo", "--port", "8600", "--db", "x.db"])
    assert args.demo is True
    assert args.port == 8600
    assert args.db == "x.db"


@pytest.mark.asyncio
async def test_run_server_spawns_and_terminates(tmp_path, monkeypatch):
    """run_server starts streamlit via injected popen and terminates it on stop."""
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # still running
    spawned = {}

    def fake_popen(cmd, **kw):
        spawned["cmd"] = cmd
        return fake_proc

    stop_event = asyncio.Event()

    async def _stopper():
        await asyncio.sleep(0.05)
        stop_event.set()

    monkeypatch.setenv("MEMEDOG_DB", str(tmp_path / "serve.db"))
    asyncio.create_task(_stopper())
    await serve.run_server(
        demo=True, port=8601, db_path=str(tmp_path / "serve.db"),
        stop_event=stop_event, popen=fake_popen,
    )
    assert "cmd" in spawned  # streamlit was launched
    fake_proc.terminate.assert_called()  # terminated on shutdown
