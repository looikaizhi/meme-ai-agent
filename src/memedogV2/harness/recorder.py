from __future__ import annotations

import os
from datetime import datetime, timezone

from memedogV2.harness.contracts import HarnessRun


class Recorder:
    """Writes a HarnessRun as JSON to runs_dir (default runs/memedogV2/)."""

    def __init__(self, runs_dir: str = "runs/memedogV2") -> None:
        self._dir = runs_dir

    def write(self, run: HarnessRun) -> str:
        os.makedirs(self._dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ca = (run.ca_address[:8] or "unknown")
        path = os.path.join(self._dir, f"{ts}-{run.run_id}-{ca}.json")
        with open(path, "w") as f:
            f.write(run.model_dump_json(indent=2))
        return path
