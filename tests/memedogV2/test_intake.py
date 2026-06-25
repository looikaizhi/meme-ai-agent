import pytest
from memedogV2.intake import AddressIntake


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
