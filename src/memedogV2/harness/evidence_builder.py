from __future__ import annotations

from typing import Any

from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.hardfilter.rules import get_path, num
from memedogV2.models.contracts import EvidenceBundle


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
