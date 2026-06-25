import os, shutil
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import ToolRegistry, GmgnCliToolSource
from memedogV2.harness.model_registry import build_backend

pytestmark = pytest.mark.live
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["deepseek", "codex"])
async def test_real_pipeline_runs_and_records(backend):
    if shutil.which("gmgn-cli") is None:
        pytest.skip("gmgn-cli not installed")
    if backend == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")
    if backend == "codex" and shutil.which("codex") is None:
        pytest.skip("codex not installed")
    cfg = load_v2_config("src/memedogV2/config_thresholds.yaml")
    reg = ToolRegistry(source=GmgnCliToolSource(GmgnCli(rate_per_sec=1.0, capacity=1)))
    runner = HarnessRunner(tool_registry=reg, backend=build_backend(backend),
                           hardfilter_cfg=cfg.hardfilter)
    run = await runner.run(USDC, "LP")
    names = [s.name for s in run.steps]
    assert names[:3] == ["read_security", "read_info", "hardfilter"]
    assert any(s.tool_calls for s in run.steps)
    if run.final_signal is not None:
        assert run.final_signal.signal.value in ("BULLISH", "BEARISH", "NEUTRAL")
