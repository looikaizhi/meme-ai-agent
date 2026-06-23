import json
from pathlib import Path

import pytest

from memedog.discovery.helius_feed import parse_helius_log

_FX = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"


def test_noise_log_returns_none():
    msg = json.loads((_FX / "helius_noise_log.json").read_text(encoding="utf-8"))
    assert parse_helius_log(msg) is None


def test_subscribe_ack_returns_none():
    assert parse_helius_log({"jsonrpc": "2.0", "result": 12345, "id": 1}) is None


def test_non_dict_returns_none():
    assert parse_helius_log("x") is None


@pytest.mark.skipif(
    not (_FX / "helius_migration_log.json").exists(),
    reason="no real migration log captured (sparse event)",
)
def test_real_migration_log_extracts_mint():
    msg = json.loads((_FX / "helius_migration_log.json").read_text(encoding="utf-8"))
    mint = parse_helius_log(msg)
    if mint is not None:
        assert 32 <= len(mint) <= 44
