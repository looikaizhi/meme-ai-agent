import pytest
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.models.contracts import EvidenceBundle


class FakeAgent:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def run(self, *, prompt, schema):
        self.calls.append({"prompt": prompt, "schema": schema})
        return self._payload


@pytest.mark.asyncio
async def test_gather_maps_payload_into_bundle():
    agent = FakeAgent({
        "smart_money_count": 4, "kol_holder_count": 2,
        "dev_created_token_count": 1, "dev_graduation_rate": 0.5,
        "historical_ath": 1.2e6,
    })
    g = EvidenceGatherer(agent=agent, max_calls=5)
    b = await g.gather("CA")
    assert isinstance(b, EvidenceBundle)
    assert b.smart_money_count == 4 and b.kol_holder_count == 2
    assert b.missing == []
    # strict schema passed to the agent
    schema = agent.calls[0]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())


@pytest.mark.asyncio
async def test_gather_records_missing_dims():
    agent = FakeAgent({
        "smart_money_count": 1, "kol_holder_count": None,
        "dev_created_token_count": None, "dev_graduation_rate": None,
        "historical_ath": None,
    })
    g = EvidenceGatherer(agent=agent, max_calls=5)
    b = await g.gather("CA")
    assert b.smart_money_count == 1
    assert "kol_holder_count" in b.missing
    assert "historical_ath" in b.missing


@pytest.mark.asyncio
async def test_prompt_includes_address_and_call_budget():
    agent = FakeAgent({k: None for k in
        ["smart_money_count","kol_holder_count","dev_created_token_count",
         "dev_graduation_rate","historical_ath"]})
    g = EvidenceGatherer(agent=agent, max_calls=3)
    await g.gather("MYCA")
    p = agent.calls[0]["prompt"]
    assert "MYCA" in p and "3" in p
