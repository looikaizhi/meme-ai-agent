"""Manual entrypoint: process one (CA, LP) through the real pipeline.

Usage: python -m memedogV2 <CA> <LP>
Requires GMGN_API_KEY in ~/.config/gmgn/.env, gmgn-cli installed, codex logged in.
"""
from __future__ import annotations

import asyncio
import os
import sys

from memedogV2.audit.debate import BullBearJudge
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.llm.codex_agent import CodexAgent
from memedogV2.orchestrator import AuditPipeline, V2Orchestrator

_CFG = os.path.join(os.path.dirname(__file__), "config_thresholds.yaml")


async def _main(ca: str, lp: str) -> None:
    cfg = load_v2_config(_CFG)
    cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
                  cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
    hf = HardFilter(cli=cli, cfg=cfg.hardfilter, on_failure=cfg.gmgn["on_failure"])
    agent = CodexAgent(cwd=os.getcwd())
    audit = AuditPipeline(
        gatherer=EvidenceGatherer(agent=agent, max_calls=cfg.gmgn["max_evidence_calls"]),
        judge=BullBearJudge(agent=agent),
    )
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process(ca, lp)
    print(sig.model_dump_json(indent=2) if sig else "DROPPED or no signal")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python -m memedogV2 <CA> <LP>")
        sys.exit(2)
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
