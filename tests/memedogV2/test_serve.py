import asyncio
from pathlib import Path

import pytest

from memedogV2 import serve


def test_build_streamlit_cmd_uses_dashboard():
    cmd = serve.build_streamlit_cmd(8602)
    assert cmd[:3]
    assert "streamlit" in cmd
    assert Path(cmd[4]).name == "app.py"
    assert Path(cmd[4]).parent.name == "dashboard"
    assert "8602" in cmd


def test_parse_args_defaults_backend_codex():
    args = serve.parse_args(["--db", "x.db", "--port", "8603"])
    assert args.backend == "codex"
    assert args.db == "x.db"
    assert args.port == 8603


@pytest.mark.asyncio
async def test_run_server_starts_feed_worker_and_dashboard(tmp_path, monkeypatch):
    class FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    class FakeFeed:
        def __init__(self):
            self.started = False

        async def run(self, stop_event):
            self.started = True
            await stop_event.wait()

    class FakeRunner:
        async def run(self, ca, lp, trace_id=""):
            raise AssertionError("worker should idle with empty intake")

    fake_feed = FakeFeed()
    fake_proc = FakeProc()
    stop = asyncio.Event()

    monkeypatch.setattr(serve, "_build_runner", lambda backend: FakeRunner())
    monkeypatch.setattr(serve, "build_telegram_feed", lambda **kwargs: fake_feed)

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(
        serve.run_server(
            backend="codex",
            port=8604,
            db_path=str(tmp_path / "v2.db"),
            stop_event=stop,
            popen=lambda cmd: fake_proc,
        ),
        stopper(),
    )

    assert fake_feed.started is True
    assert fake_proc.terminated is True


@pytest.mark.asyncio
async def test_worker_does_not_cancel_slow_processing():
    from memedogV2.intake import AddressIntake, IntakeProcessor

    class SlowRunner:
        def __init__(self):
            self.done = asyncio.Event()

        async def run(self, ca, lp, trace_id=""):
            await asyncio.sleep(1.2)
            self.done.set()

    intake = AddressIntake()
    intake.enqueue("CA1", "LP1")
    runner = SlowRunner()
    processor = IntakeProcessor(intake=intake, runner=runner)
    stop = asyncio.Event()

    task = asyncio.create_task(serve._worker(processor, stop))
    try:
        await asyncio.wait_for(runner.done.wait(), timeout=2.0)
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert runner.done.is_set()
