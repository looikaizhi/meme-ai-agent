import json
from pathlib import Path

from memedog.discovery.pumpportal import parse_migration_message

_FX = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"


def _load(name: str):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def test_parse_real_migration_returns_mint():
    msg = _load("pumpportal_migration.json")
    assert parse_migration_message(msg) == "8yo564u5NKNzKV3jWQTSqSxXXFX69ALgweu4c8eapump"


def test_parse_subscribe_ack_returns_none():
    msg = _load("pumpportal_subscribe_ack.json")
    assert parse_migration_message(msg) is None


def test_parse_wrong_txtype_returns_none():
    assert parse_migration_message({"txType": "create", "mint": "X"}) is None


def test_parse_missing_mint_returns_none():
    assert parse_migration_message({"txType": "migrate"}) is None


def test_parse_non_dict_returns_none():
    assert parse_migration_message("garbage") is None
    assert parse_migration_message(None) is None
