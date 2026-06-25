import json
import pytest
from memedogV2.llm.codex_agent import CodexAgent


class FakeExec:
    def __init__(self, last_message):
        self._msg = last_message
        self.calls = []

    async def __call__(self, *, prompt, schema, cwd):
        self.calls.append({"prompt": prompt, "schema": schema})
        return self._msg


@pytest.mark.asyncio
async def test_run_returns_parsed_json():
    fake = FakeExec(json.dumps({"signal": "BULLISH", "recommended": True}))
    agent = CodexAgent(executor=fake)
    out = await agent.run(prompt="judge this", schema={"type": "object"})
    assert out == {"signal": "BULLISH", "recommended": True}
    assert fake.calls[0]["schema"] == {"type": "object"}


@pytest.mark.asyncio
async def test_run_raises_on_unparseable():
    fake = FakeExec("not json at all")
    agent = CodexAgent(executor=fake)
    with pytest.raises(ValueError):
        await agent.run(prompt="x", schema={"type": "object"})
