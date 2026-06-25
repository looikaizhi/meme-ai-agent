import pytest
from memedogV2.harness.contracts import HarnessRun
from memedogV2.intake import AddressIntake, IntakeProcessor


@pytest.mark.asyncio
async def test_enqueue_then_drain_one():
    q = AddressIntake()
    tid = q.enqueue("CA1", "LP1")
    assert isinstance(tid, str) and tid
    item = await q.get()
    assert item.ca_address == "CA1" and item.lp_address == "LP1"
    assert item.trace_id == tid


@pytest.mark.asyncio
async def test_dedup_same_ca_not_queued_twice():
    q = AddressIntake()
    q.enqueue("CA1", "LP1")
    q.enqueue("CA1", "LP1")     # duplicate ignored
    assert q.size() == 1


@pytest.mark.asyncio
async def test_dedup_returns_empty_trace_for_duplicate():
    q = AddressIntake()
    first = q.enqueue("CA1", "LP1")
    dup = q.enqueue("CA1", "LP1")
    assert first and dup == ""


class FakeRunner:
    def __init__(self):
        self.calls = []

    async def run(self, ca, lp, trace_id="", *, source="", stage="unknown"):
        self.calls.append((ca, lp, trace_id, source, stage))
        return HarnessRun(run_id="run1", ca_address=ca, backend="fake", mode="production")


@pytest.mark.asyncio
async def test_processor_passes_intake_item_to_runner():
    q = AddressIntake()
    tid = q.enqueue("CA1", "LP1")
    runner = FakeRunner()
    processor = IntakeProcessor(intake=q, runner=runner)

    run = await processor.process_next()

    assert runner.calls == [("CA1", "LP1", tid, "", "unknown")]
    assert run.ca_address == "CA1"
    assert q.size() == 0


@pytest.mark.asyncio
async def test_processor_drains_available_items_in_order():
    q = AddressIntake()
    tid1 = q.enqueue("CA1", "LP1")
    tid2 = q.enqueue("CA2", "LP2")
    runner = FakeRunner()
    processor = IntakeProcessor(intake=q, runner=runner)

    runs = await processor.drain_available()

    assert [r.ca_address for r in runs] == ["CA1", "CA2"]
    assert runner.calls == [
        ("CA1", "LP1", tid1, "", "unknown"),
        ("CA2", "LP2", tid2, "", "unknown"),
    ]
    assert q.size() == 0
