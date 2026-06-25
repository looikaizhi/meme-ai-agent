from memedogV2.audit.prompts import (
    evidence_text, analyst_prompt, judge_prompt, ANALYST_SCHEMA, JUDGE_SCHEMA,
)
from memedogV2.models.contracts import EvidenceBundle


def test_schemas_are_strict():
    for schema in (ANALYST_SCHEMA, JUDGE_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"].keys())


def test_evidence_text_drops_none_and_lists_missing():
    b = EvidenceBundle(ca_address="CA", smart_money_count=4, missing=["historical_ath"])
    txt = evidence_text(b)
    assert "smart_money_count" in txt and "4" in txt
    assert "historical_ath" in txt          # surfaced as missing
    assert "null" not in txt                # None fields filtered out


def test_role_prompts_label_their_role():
    b = EvidenceBundle(ca_address="CA")
    assert "BULL" in analyst_prompt("bull", b)
    assert "BEAR" in analyst_prompt("bear", b)
    jp = judge_prompt(b, bull={"thesis": "x", "points": []}, bear={"thesis": "y", "points": []})
    assert "JUDGE" in jp and "BULL" in jp and "BEAR" in jp
