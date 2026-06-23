"""Tests for deterministic narrative classification."""
from memedog.enricher.narrative import classify_narrative


def test_animal_meme():
    n = classify_narrative("QDOG", "Quantum Dog")
    assert n.category == "animal"
    assert "dog" in n.matched_keywords
    assert n.available is True


def test_ai_meme():
    n = classify_narrative("GROKAI", "Grok AI Agent")
    assert n.category == "ai"
    assert "grok" in n.meme_collision  # grok is a known winner


def test_political_meme():
    n = classify_narrative("TRUMPWIN", "Trump 2028")
    assert n.category == "political"
    assert "trump" in n.meme_collision


def test_finance_utility_name():
    n = classify_narrative("ASSETFUND", "Asset Funds Protocol")
    assert n.category == "finance_utility"


def test_unknown_falls_back():
    n = classify_narrative("XQZ", "Xqzzy")
    assert n.category == "unknown"
    assert n.matched_keywords == []


def test_meme_collision_detected():
    n = classify_narrative("BONKINU", "Bonk Inu")
    assert "bonk" in n.meme_collision
    assert n.category == "animal"  # inu is animal


def test_never_raises_on_weird_input():
    n = classify_narrative("", "")
    assert n.category == "unknown"


def test_summary_is_non_empty_for_known():
    n = classify_narrative("CATGPT", "Cat GPT")
    assert isinstance(n.summary, str) and n.summary != ""


def test_chain_token_is_finance_not_ai():
    n = classify_narrative("CHAIN", "Chain Finance")
    assert n.category == "finance_utility"  # 'ai' substring no longer steals 'chain'


def test_money_token_not_culture():
    n = classify_narrative("MONEY", "Money Flow")
    assert n.category != "culture"  # 'mon' removed


def test_grokai_still_ai_via_grok():
    n = classify_narrative("GROKAI", "Grok AI Agent")
    assert n.category == "ai"  # matched via 'grok', not bare 'ai'


def test_exception_path_returns_unavailable(monkeypatch):
    # force the inner logic to raise → defensive available=False branch
    import memedog.enricher.narrative as nar
    monkeypatch.setattr(nar, "_CATEGORY_KEYWORDS", None)  # iterating None raises
    n = nar.classify_narrative("X", "Y")
    assert n.available is False
