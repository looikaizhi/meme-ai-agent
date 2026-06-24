import pytest

from memedog.clients.base import DataSourceError


def test_parse_galaxy_score_ok():
    from memedog.clients.lunarcrush import _parse_galaxy_score
    assert _parse_galaxy_score({"data": {"galaxy_score": 72.5}}) == 72.5


def test_parse_galaxy_score_missing_returns_none():
    from memedog.clients.lunarcrush import _parse_galaxy_score
    assert _parse_galaxy_score({"data": {}}) is None
    assert _parse_galaxy_score({}) is None
    assert _parse_galaxy_score(None) is None
    assert _parse_galaxy_score({"data": {"galaxy_score": "x"}}) is None


@pytest.mark.asyncio
async def test_get_galaxy_score_degrades_to_none_on_error():
    from memedog.clients.lunarcrush import LunarCrushClient

    class _Raising(LunarCrushClient):
        async def get_json(self, url, **kwargs):
            raise DataSourceError("boom")

    c = _Raising(api_key="k")
    try:
        assert await c.get_galaxy_score("BONK") is None
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_get_galaxy_score_degrades_on_non_datasource_error():
    from memedog.clients.lunarcrush import LunarCrushClient

    class _BadJson(LunarCrushClient):
        async def get_json(self, url, **kwargs):
            raise ValueError("not json")  # simulates JSONDecodeError escaping base client

    c = _BadJson(api_key="k")
    try:
        assert await c.get_galaxy_score("BONK") is None
    finally:
        await c.aclose()


def test_constructor_rejects_empty_api_key():
    from memedog.clients.lunarcrush import LunarCrushClient
    with pytest.raises(ValueError):
        LunarCrushClient(api_key="")


def test_symbol_is_url_encoded():
    from memedog.clients.lunarcrush import LunarCrushClient

    captured = {}

    class _Capture(LunarCrushClient):
        async def get_json(self, url, **kwargs):
            captured["url"] = url
            return {"data": {"galaxy_score": 1.0}}

    import asyncio

    async def _run():
        c = _Capture(api_key="k")
        try:
            await c.get_galaxy_score("$WIF/X")
        finally:
            await c.aclose()

    asyncio.run(_run())
    assert "$" not in captured["url"] and "%24" in captured["url"]
    assert "/X/v1" not in captured["url"]  # the '/' in the symbol must be encoded
