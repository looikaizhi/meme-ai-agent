import json
from memedogV2.harness.evidence_builder import build_evidence
from memedogV2.models.contracts import EvidenceBundle


def test_build_evidence_from_real_info_fixture():
    info = json.load(open("tests/memedogV2/fixtures/info.json"))
    bundle = build_evidence(facts=info, ca="EPjFW")
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.smart_money_count is not None
    assert bundle.kol_holder_count is not None
    assert bundle.dev_graduation_rate is None
    assert "dev_graduation_rate" in bundle.missing


def test_build_evidence_marks_absent_fields_missing():
    bundle = build_evidence(facts={}, ca="CA")  # empty facts
    assert bundle.smart_money_count is None
    assert "smart_money_count" in bundle.missing
    assert "kol_holder_count" in bundle.missing
