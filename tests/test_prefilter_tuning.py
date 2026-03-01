"""Session 16 Task B: prefilter Stage A tuning tests

テスト方針:
- 半導体関連記事がStage Aを通過する（PASS）
- 完全無関係記事は通過しない（DROP）
- near-miss: 半導体キーワード1個だけの記事は閾値未満（DROP、ただしfallbackで拾える）
- fallback: Stage A全DROP時にscore>0の記事が返る

TestPrefilterKeywords (6本):
  1. test_export_control_article_passes — 輸出規制記事（export control + semiconductor）
  2. test_hbm_foundry_article_passes — HBM+foundry記事
  3. test_earnings_guidance_article_passes — 決算ガイダンス記事
  4. test_irrelevant_food_article_dropped — 料理記事
  5. test_irrelevant_travel_article_dropped — 旅行記事
  6. test_near_miss_single_keyword_below_threshold — キーワード1個(1.5)は閾値未満

TestPrefilterFallback (2本):
  7. test_fallback_returns_score_positive — Stage A全DROPでもscore>0返却
  8. test_fallback_empty_when_all_zero — 全score=0なら空リスト
"""
from __future__ import annotations

import pytest

from sector_event_radar.models import Article
from sector_event_radar.prefilter import prefilter, ScoredArticle


# ── テスト用キーワード辞書（config.yaml Tier 1-4の代表を網羅）──
TEST_KEYWORDS = {
    "semiconductor": 3.0,
    "AI chip": 3.0,
    "export control": 3.0,
    "NVIDIA": 3.0,
    "chip": 2.5,
    "TSMC": 2.5,
    "foundry": 2.5,
    "HBM": 2.5,
    "fab": 2.5,
    "export ban": 2.5,
    "entity list": 2.5,
    "Intel": 2.0,
    "Samsung": 2.0,
    "earnings": 2.0,
    "guidance": 2.0,
    "DRAM": 1.5,
    "NAND": 1.5,
    "mass production": 1.5,
    "packaging": 1.5,
    "3nm": 1.5,
    "capacity expansion": 1.5,
}

THRESHOLD = 3.0  # config.yaml更新後の値


def _article(title: str, body: str = "") -> Article:
    return Article(
        title=title,
        url=f"https://example.com/{title[:20].replace(' ', '-').lower()}",
        published="2026-03-01T00:00:00Z",
        body=body,
    )


# ══════════════════════════════════════════════════════════
# TestPrefilterKeywords (6本)
# ══════════════════════════════════════════════════════════

class TestPrefilterKeywords:
    """キーワードマッチでStage Aを通過/DROPする挙動"""

    def test_export_control_article_passes(self):
        """輸出規制記事: 'export control'(3.0) + 'semiconductor'(3.0) = 6.0 ≥ 3.0"""
        articles = [_article(
            "US Tightens Export Control on Semiconductor Equipment to China",
            "The Biden administration announced new export control measures "
            "targeting advanced semiconductor manufacturing equipment.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) == 1
        assert result[0].relevance_score >= THRESHOLD

    def test_hbm_foundry_article_passes(self):
        """HBM+foundry記事: 'HBM'(2.5) + 'foundry'(2.5) = 5.0 ≥ 3.0"""
        articles = [_article(
            "TSMC Ramps HBM Packaging at Advanced Foundry Facility",
            "TSMC is expanding its HBM advanced packaging capacity at its foundry.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) >= 1
        assert result[0].relevance_score >= THRESHOLD

    def test_earnings_guidance_article_passes(self):
        """決算ガイダンス記事: 'NVIDIA'(3.0) + 'earnings'(2.0) + 'guidance'(2.0) = 7.0"""
        articles = [_article(
            "NVIDIA Beats Earnings Estimates, Raises Guidance for Q2",
            "NVIDIA reported strong earnings and raised guidance.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) == 1
        assert result[0].relevance_score >= THRESHOLD

    def test_irrelevant_food_article_dropped(self):
        """料理記事: キーワードゼロ → score=0 → DROP"""
        articles = [_article(
            "How RFID Labels Could Help Tackle $540B Food Waste Losses in 2026",
            "RFID technology in food supply chain management for reducing waste.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) == 0

    def test_irrelevant_travel_article_dropped(self):
        """旅行記事: キーワードゼロ → score=0 → DROP"""
        articles = [_article(
            "10 Best Beach Destinations for Summer 2026 Vacations",
            "From Maldives to Bali, here are the top beach getaways.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) == 0

    def test_near_miss_single_keyword_below_threshold(self):
        """キーワード1個('packaging'=1.5)が1回だけ → score=1.5 < 3.0 → DROP"""
        articles = [_article(
            "New Trends in Electronics Packaging for IoT Devices",
            "Innovative solutions for next-generation IoT applications.",
        )]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=THRESHOLD)
        assert len(result) == 0


# ══════════════════════════════════════════════════════════
# TestPrefilterFallback (2本)
# ══════════════════════════════════════════════════════════

class TestPrefilterFallback:
    """Stage A全DROP時のフォールバック挙動"""

    def test_fallback_returns_score_positive(self):
        """Stage A全DROP、ただしscore>0の記事あり → fallbackで返される"""
        articles = [
            _article("Random article about cooking", "No semiconductor keywords here."),
            _article("DRAM Prices Stabilize", "DRAM prices have stabilized."),
        ]
        # threshold=10.0に上げて全DROP強制、ただしDRAM記事はscore>0
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=10.0)
        assert len(result) >= 1
        assert any("DRAM" in r.article.title for r in result)

    def test_fallback_empty_when_all_zero(self):
        """全記事score=0 → fallbackも空"""
        articles = [
            _article("Cooking Tips for Beginners", "How to boil water and chop onions."),
            _article("Best Vacation Spots 2026", "Beaches and mountains for your getaway."),
        ]
        result = prefilter(articles, TEST_KEYWORDS, stage_a_threshold=10.0)
        assert len(result) == 0
