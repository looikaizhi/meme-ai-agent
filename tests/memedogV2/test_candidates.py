import json

import pytest

from memedogV2.candidates import (
    extract_market_candidates,
    fetch_gmgn_market_candidates,
)


def test_extracts_trending_rank_candidates():
    payload = {
        "code": 0,
        "data": {
            "rank": [
                {"address": "CA1", "pool_address": "LP1"},
                {"address": "CA1", "pool_address": "LP_DUP"},
                {"address": "CA2"},
            ]
        },
    }

    out = extract_market_candidates(payload, source="gmgn_trending", limit=5)

    assert [item.ca_address for item in out] == ["CA1", "CA2"]
    assert out[0].lp_address == "LP1"
    assert out[0].source == "gmgn_trending"


def test_extracts_signal_candidates_from_nested_data():
    payload = [
        {
            "token_address": "CA1",
            "data": {"address": "CA1_NESTED", "pool_address": "LP1"},
        },
        {
            "data": {"address": "CA2", "pool_address": "LP2"},
        },
    ]

    out = extract_market_candidates(payload, source="gmgn_signal", limit=None)

    assert [(item.ca_address, item.lp_address) for item in out] == [
        ("CA1", "LP1"),
        ("CA2", "LP2"),
    ]


def test_extracts_trenches_category_candidates():
    payload = {
        "completed": [{"address": "CA1", "pool_address": "LP1"}],
        "new_creation": [{"address": "CA2"}],
        "pump": [{"address": "CA1"}],
    }

    out = extract_market_candidates(payload, source="gmgn_trenches", limit=None)

    assert [item.ca_address for item in out] == ["CA2", "CA1"]
    assert [item.stage for item in out] == ["new_creation", "completed"]


@pytest.mark.asyncio
async def test_fetch_gmgn_trending_builds_command_and_normalizes():
    calls = []

    async def runner(args):
        calls.append(args)
        return (
            0,
            json.dumps({"data": {"rank": [{"address": "CA1", "pool_address": "LP1"}]}}),
            "",
        )

    out = await fetch_gmgn_market_candidates(
        "trending",
        chain="sol",
        limit=3,
        interval="1m",
        order_by="volume",
        direction="desc",
        filters=["renounced", "has_social"],
        runner=runner,
    )

    assert out[0].ca_address == "CA1"
    assert calls == [[
        "market",
        "trending",
        "--chain",
        "sol",
        "--interval",
        "1m",
        "--limit",
        "3",
        "--order-by",
        "volume",
        "--direction",
        "desc",
        "--filter",
        "renounced",
        "--filter",
        "has_social",
        "--raw",
    ]]
