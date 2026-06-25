from __future__ import annotations

from typing import Any

from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.hardfilter.rules import get_path, num
from memedogV2.models.contracts import EvidenceBundle
from memedogV2.sources.base import Facts


def _int(facts: dict, key: str):
    v = get_path(facts, FIELD_MAP[key])
    n = num(v)
    return int(n) if n is not None else None


def _float(facts: dict, key: str):
    return num(get_path(facts, FIELD_MAP[key]))


def build_evidence(*, facts: dict[str, Any], ca: str) -> EvidenceBundle:
    """Deterministically extract LLM evidence from already-fetched gmgn facts."""
    smart = _int(facts, "smart_wallets")
    kol = _int(facts, "renowned_wallets")
    dev_created = _int(facts, "dev_created_count")
    ath = _float(facts, "dev_ath_mc")
    graduation = None  # no gmgn source for dev graduation rate

    fields = {
        "smart_money_count": smart,
        "kol_holder_count": kol,
        "dev_created_token_count": dev_created,
        "dev_graduation_rate": graduation,
        "historical_ath": ath,
    }
    missing = [k for k, v in fields.items() if v is None]
    return EvidenceBundle(ca_address=ca, missing=missing, **fields)


def build_evidence_from_facts(*, facts: Facts, ca: str) -> EvidenceBundle:
    """Extract LLM evidence from canonical Facts (multi-source resolver output)."""
    fields = {
        "smart_money_count": facts.smart_money_count,
        "kol_holder_count": facts.kol_count,
        "dev_created_token_count": facts.dev_created_count,
        "dev_graduation_rate": None,
        "historical_ath": facts.historical_ath,
    }
    missing = [k for k, v in fields.items() if v is None]
    return EvidenceBundle(ca_address=ca, missing=missing, **fields)


def important_missing(facts: Facts) -> list[str]:
    """Canonical fact fields that came back unavailable — surfaced to the audit so
    the models treat them as unknown (and never invent them)."""
    from memedogV2.sources.base import ALL_FIELDS
    return [name for name in ALL_FIELDS if getattr(facts, name) is None]
