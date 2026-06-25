"""Manual entrypoint: process one (CA, LP) through the harness production path.

Usage: python -m memedogV2 <CA> <LP> [backend]   # backend: deepseek (default) | codex
Requires GMGN_API_KEY in ~/.config/gmgn/.env, gmgn-cli installed; DEEPSEEK_API_KEY or codex login.
"""
from __future__ import annotations

import asyncio
import os
import sys

from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.harness.model_registry import build_backend
from memedogV2.harness.recorder import Recorder
from memedogV2.harness.runner import HarnessRunner
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.sources.helius_source import HeliusSource
from memedogV2.sources.resolver import DataResolver
from memedogV2.sources.rugcheck_source import RugCheckSource

_CFG = os.path.join(os.path.dirname(__file__), "config_thresholds.yaml")


async def _main(ca: str, lp: str, backend_name: str) -> None:
    cfg = load_v2_config(_CFG)
    cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
                  cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
    resolver = DataResolver(sources={
        "rugcheck": RugCheckSource(),
        "gmgn": GmgnSource(cli=cli, max_retries=cfg.gmgn.get("max_retries", 2)),
        "helius": HeliusSource(),
    })
    runner = HarnessRunner(resolver=resolver,
                           backend=build_backend(backend_name, cwd=os.getcwd()),
                           hardfilter_cfg=cfg.hardfilter,
                           recorder=Recorder())
    run = await runner.run(ca, lp)
    print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("usage: python -m memedogV2 <CA> <LP> [deepseek|codex]")
        sys.exit(2)
    name = sys.argv[3] if len(sys.argv) == 4 else "deepseek"
    asyncio.run(_main(sys.argv[1], sys.argv[2], name))
