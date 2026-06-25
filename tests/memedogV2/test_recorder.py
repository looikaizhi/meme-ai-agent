import json
import os
from memedogV2.harness.recorder import Recorder
from memedogV2.harness.contracts import HarnessRun, StepResult, StepStatus


def test_recorder_writes_json_run_file(tmp_path):
    run = HarnessRun(run_id="r1", ca_address="CAabcdef", backend="fake", mode="production")
    run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK))
    rec = Recorder(runs_dir=str(tmp_path))
    path = rec.write(run)
    assert path.endswith(".json")
    data = json.load(open(path))
    assert data["run_id"] == "r1" and data["steps"][0]["name"] == "hardfilter"
    assert "r1" in os.path.basename(path)
