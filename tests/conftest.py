"""Shared test helpers: load real captured fixtures from tests/fixtures/."""
import json
from pathlib import Path

import pytest

_FX = Path(__file__).parent / "fixtures"


def load_fixture(relpath: str):
    """Load a real captured fixture body.

    ``.json`` files are parsed; any other suffix is returned as text.
    Example: ``load_fixture("dexscreener/tokens_bonk.json")``.
    """
    p = _FX / relpath
    text = p.read_text(encoding="utf-8")
    return json.loads(text) if p.suffix == ".json" else text


@pytest.fixture
def fixture():
    """Pytest fixture exposing the load_fixture helper."""
    return load_fixture
