from memedog.discovery.buffer import MintBuffer


def test_add_and_recent_returns_in_insertion_order():
    b = MintBuffer(ttl_sec=60)
    b.add("A")
    b.add("B")
    b.add("C")
    assert b.recent() == ["A", "B", "C"]


def test_recent_is_non_destructive():
    b = MintBuffer(ttl_sec=60)
    b.add("A")
    assert b.recent() == ["A"]
    assert b.recent() == ["A"]


def test_dedup_keeps_first_timestamp():
    b = MintBuffer(ttl_sec=60)
    b.add("A")
    b.add("A")
    assert b.recent() == ["A"]


def test_ttl_expiry_drops_old_entries():
    now = [1000.0]
    b = MintBuffer(ttl_sec=60, clock=lambda: now[0])
    b.add("OLD")
    now[0] = 1061.0
    b.add("NEW")
    assert b.recent() == ["NEW"]
