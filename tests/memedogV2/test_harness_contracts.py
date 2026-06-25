from memedogV2.harness.contracts import (
    StepStatus, ToolCallRecord, ModelCallRecord, StepResult, HarnessRun,
)


def test_step_result_defaults_and_records():
    sr = StepResult(name="read_security", status=StepStatus.OK)
    assert sr.tool_calls == [] and sr.model_calls == []
    assert sr.error == ""


def test_harness_run_collects_steps_and_signal():
    run = HarnessRun(run_id="r1", ca_address="CA", backend="fake", mode="production")
    run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK))
    assert run.steps[0].name == "hardfilter"
    assert run.final_signal is None


def test_tool_and_model_call_records():
    t = ToolCallRecord(tool="gmgn-cli", command="token security CA",
                       exit_status=0, duration_ms=12.0)
    m = ModelCallRecord(backend="deepseek", role="bull", schema_valid=True, duration_ms=900.0)
    assert t.exit_status == 0 and m.schema_valid is True
