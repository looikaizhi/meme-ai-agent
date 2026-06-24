from __future__ import annotations

from memedogV2.models.contracts import EvidenceBundle

_FIELDS = ["smart_money_count", "kol_holder_count", "dev_created_token_count",
           "dev_graduation_rate", "historical_ath"]

# STRICT schema: additionalProperties false + every property required (nullable
# via ["type","null"]). Scalar-only — free-form objects are unreliable in strict mode.
_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "smart_money_count": {"type": ["integer", "null"]},
        "kol_holder_count": {"type": ["integer", "null"]},
        "dev_created_token_count": {"type": ["integer", "null"]},
        "dev_graduation_rate": {"type": ["number", "null"]},
        "historical_ath": {"type": ["number", "null"]},
    },
    "required": _FIELDS,
}


class EvidenceGatherer:
    """One codex-agent call that uses gmgn-skills to assemble a shared EvidenceBundle.

    The bundle is gathered once and read by both bull and bear analysts, so the
    (rate-limited) gmgn calls happen a single time per token.
    """

    def __init__(self, *, agent, max_calls: int = 5) -> None:
        self._agent = agent
        self._max_calls = max_calls

    def _prompt(self, ca: str) -> str:
        return (
            "Use the gmgn-token, gmgn-track and gmgn-market skills (the gmgn-cli tool) "
            f"to investigate Solana token {ca}. Run at most {self._max_calls} gmgn-cli "
            "calls total. Collect these scalar signals: "
            "smart_money_count (info wallet_tags_stat.smart_wallets), "
            "kol_holder_count (info wallet_tags_stat.renowned_wallets), "
            "dev_created_token_count (info dev.creator_open_count), "
            "dev_graduation_rate (fraction of the dev's past tokens that graduated, "
            "if knowable, else null), "
            "historical_ath (dev.ath_token_info.ath_mc as a number if available). "
            "Return JSON with exactly these keys; use null for anything you cannot fetch."
        )

    async def gather(self, ca: str) -> EvidenceBundle:
        payload = await self._agent.run(prompt=self._prompt(ca), schema=_EVIDENCE_SCHEMA)
        data = {k: payload.get(k) for k in _FIELDS}
        missing = [k for k in _FIELDS if data.get(k) is None]
        return EvidenceBundle(ca_address=ca, missing=missing, **data)
