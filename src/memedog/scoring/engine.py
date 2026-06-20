"""ScoreEngine: aggregates dimension scores into a final Score.

Accepts a ScoringConfig (not the full Config) so it stays decoupled from
environment/secrets layers.

Weight renormalization algorithm:
1. For each dimension, base_weight = cfg.weights[name].
2. If that dimension's info is unavailable, effective_weight =
   base_weight * cfg.missing_dimension_weight_factor.
3. Sum all effective_weights → total_w.
4. final_weight = effective_weight / total_w  (renormalize to sum=1).
5. weighted = raw * final_weight; total = sum(weighted).

Edge cases:
- If total_w == 0 (e.g. missing_dimension_weight_factor=0 and all dims
  unavailable), fall back to equal weights (0.25 each) so the pipeline
  never crashes ("降级而非崩溃").
- cfg.weights must contain all four keys {safety, holders, momentum, social};
  missing keys raise ValueError at construction time.
"""
from __future__ import annotations

import logging

from memedog.config.settings import ScoringConfig
from memedog.models.score import DimensionScore, Score
from memedog.models.snapshot import TokenSnapshot
from memedog.scoring.dimensions import (
    score_holders,
    score_momentum,
    score_safety,
    score_social,
)

_REQUIRED_WEIGHT_KEYS = {"safety", "holders", "momentum", "social"}
_logger = logging.getLogger(__name__)


class ScoreEngine:
    """Compute a composite Score from a TokenSnapshot."""

    def __init__(self, cfg: ScoringConfig) -> None:
        # Fix 2: validate that all four weight keys are present at construction time
        missing = _REQUIRED_WEIGHT_KEYS - set(cfg.weights.keys())
        if missing:
            raise ValueError(f"cfg.weights missing keys: {missing}")
        self._cfg = cfg

    def score(self, snapshot: TokenSnapshot) -> Score:
        cfg = self._cfg

        # 1. Compute raw dimension scores (weight/weighted left at 0.0 by scorers)
        raw_dims: list[tuple[DimensionScore, bool]] = [
            (score_safety(snapshot.safety, cfg), snapshot.safety.available),
            (score_holders(snapshot.holders, cfg), snapshot.holders.available),
            (score_momentum(snapshot.momentum, cfg), snapshot.momentum.available),
            (score_social(snapshot.social, cfg), snapshot.social.available),
        ]

        # 2. Compute effective weights (reduce if unavailable)
        effective_weights: list[float] = []
        for ds, available in raw_dims:
            base = cfg.weights[ds.name]
            eff = base if available else base * cfg.missing_dimension_weight_factor
            effective_weights.append(eff)

        total_w = sum(effective_weights)

        # Fix 1: guard against division-by-zero when total_w == 0
        # (can happen when missing_dimension_weight_factor=0 and all dims unavailable)
        if total_w == 0.0:
            _logger.warning(
                "ScoreEngine: total effective weight is 0 — falling back to equal "
                "weights (0.25 each). This happens when missing_dimension_weight_factor=0 "
                "and all dimensions are unavailable."
            )
            n = len(effective_weights)
            effective_weights = [1.0 / n] * n
            total_w = 1.0

        # 3. Renormalize and build final DimensionScore objects
        final_dims: list[DimensionScore] = []
        for (ds, _available), eff_w in zip(raw_dims, effective_weights):
            final_weight = eff_w / total_w
            weighted = ds.raw * final_weight
            final_dims.append(
                DimensionScore(
                    name=ds.name,
                    raw=ds.raw,
                    weight=final_weight,
                    weighted=weighted,
                    notes=ds.notes,
                )
            )

        total = sum(d.weighted for d in final_dims)

        return Score(
            mint=snapshot.candidate.mint,
            total=total,
            dimensions=final_dims,
            trace_id=snapshot.candidate.trace_id,
        )
