from memedogV2.sources.base import Facts, FIELD_PRIORITY, ALL_FIELDS


def test_facts_defaults_all_none():
    f = Facts()
    for name in ALL_FIELDS:
        assert getattr(f, name) is None


def test_priority_table_covers_every_field_and_orders_sources():
    for name in ALL_FIELDS:
        assert name in FIELD_PRIORITY
        for src in FIELD_PRIORITY[name]:
            assert src in ("rugcheck", "gmgn", "helius")
    assert FIELD_PRIORITY["liquidity_usd"] == ["gmgn"]
    assert FIELD_PRIORITY["mint_revoked"][0] == "rugcheck"
    assert FIELD_PRIORITY["top10_rate"] == ["rugcheck", "gmgn", "helius"]
