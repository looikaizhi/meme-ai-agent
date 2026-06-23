"""Deterministic narrative classification from a token's symbol/name.

No network, no LLM, never raises. Answers "does this coin have a memeable hook"
purely from its name — a cheap attention proxy.
"""
from __future__ import annotations

from memedog.models import NarrativeInfo

# Category keyword tables (classification logic; ordered by priority).
# Scores for these categories live in thresholds.yaml (tunable), not here.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("animal", ["dog", "doge", "inu", "shib", "cat", "kitty", "pepe", "frog",
                "bear", "bull", "ape", "monkey", "wif", "hippo", "penguin"]),
    ("ai", ["gpt", "agent", "grok", "neural", "llm", "gpu"]),
    ("political", ["trump", "biden", "maga", "election", "vance", "boden", "potus"]),
    ("culture", ["meme", "chad", "wojak", "giga", "based",
                 "pokemon", "anime"]),
    ("finance_utility", ["fund", "capital", "finance", "protocol", "dao", "swap",
                         "chain", "pay", "asset", "yield", "stake", "cash"]),
]

# Known runaway memes a new name may echo (context + scoring bonus).
_MEME_WINNERS = ["wif", "pepe", "bonk", "doge", "shib", "cat", "grok", "trump", "musk"]

_CATEGORY_LABEL = {
    "animal": "动物系 meme",
    "ai": "AI/agent 叙事",
    "political": "政治/名人事件",
    "culture": "网络文化/游戏",
    "finance_utility": "金融/工具型命名",
    "unknown": "无明显叙事钩子",
}


def classify_narrative(symbol: str, name: str) -> NarrativeInfo:
    """Classify a token's narrative from its symbol + name. Never raises."""
    try:
        text = f"{symbol or ''} {name or ''}".lower()

        category = "unknown"
        matched: list[str] = []
        for cat, keywords in _CATEGORY_KEYWORDS:
            hits = [kw for kw in keywords if kw in text]
            if hits:
                category = cat
                matched = hits
                break

        collisions = [w for w in _MEME_WINNERS if w in text]

        label = _CATEGORY_LABEL.get(category, _CATEGORY_LABEL["unknown"])
        if collisions:
            summary = f"{label};呼应已知 meme: {', '.join(collisions)}"
        else:
            summary = label

        return NarrativeInfo(
            available=True,
            category=category,
            matched_keywords=matched,
            meme_collision=collisions,
            summary=summary,
        )
    except Exception:  # noqa: BLE001 — deterministic, but stay defensive
        return NarrativeInfo(available=False)
