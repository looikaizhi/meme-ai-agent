from memedogV2.models.contracts import (
    SignalKind, HardFilterResult, EvidenceBundle, Signal,
)


def test_hardfilter_result_defaults():
    r = HardFilterResult(ca_address="CA", lp_address="LP")
    assert r.passed is False
    assert r.dropped == [] and r.flagged == []
    assert r.facts == {}


def test_evidence_bundle_holds_optional_signals():
    e = EvidenceBundle(ca_address="CA", smart_money_count=3, kol_holder_count=1)
    assert e.smart_money_count == 3
    assert e.dev_graduation_rate is None  # optional/degraded allowed


def test_signal_recommended_and_kind():
    s = Signal(
        ca_address="CA", signal=SignalKind.BULLISH, recommended=True,
        confidence=0.8, rationale="strong smart money", evidence_refs=["smart_money_count"],
    )
    assert s.signal is SignalKind.BULLISH
    assert s.recommended is True
    assert s.confidence == 0.8
