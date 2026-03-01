from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Sequence

from .models import Article

logger = logging.getLogger(__name__)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False


@dataclass(frozen=True)
class ScoredArticle:
    article: Article
    relevance_score: float


def _kw_score(text: str, keywords: Dict[str, float]) -> float:
    t = text.lower()
    score = 0.0
    for kw, w in keywords.items():
        kw2 = kw.lower()
        if not kw2:
            continue
        occ = t.count(kw2)
        if occ <= 0:
            continue
        score += float(w) * min(3, occ)  # 極端な連呼で暴れないよう上限
    return score


def prefilter(
    articles: Sequence[Article],
    keywords: Dict[str, float],
    stage_a_threshold: float = 4.0,
    stage_b_top_k: int = 30,
) -> List[ScoredArticle]:
    """Spec M1: 2段階記事フィルタ。
    - Stage A: keyword weighted score（thresholdは config.yaml で可変、デフォルト4.0）
    - Stage B: TF-IDF cosine similarity, top_k only (if sklearn available)
    - Stage A=0件時: score>0 の上位K件をfallbackで返す（sklearn有無に関わらず）
    """
    # ── Stage A: keyword scoring ──
    all_scored: List[ScoredArticle] = []
    scored_a: List[ScoredArticle] = []
    dropped_a: int = 0
    for a in articles:
        text = f"{a.title}\n{a.body}"
        s = _kw_score(text, keywords)
        sa = ScoredArticle(article=a, relevance_score=s)
        all_scored.append(sa)
        if s >= stage_a_threshold:
            scored_a.append(sa)
            logger.debug(
                "Stage A PASS: score=%.1f title='%s'",
                s, a.title[:80],
            )
        else:
            dropped_a += 1
            logger.debug(
                "Stage A DROP: score=%.1f (< %.1f) title='%s'",
                s, stage_a_threshold, a.title[:80],
            )

    logger.info(
        "Prefilter Stage A: %d/%d passed (threshold=%.1f, dropped=%d)",
        len(scored_a), len(articles), stage_a_threshold, dropped_a,
    )

    # Stage A が 0件の場合、上位5件のスコアをログ出力（閾値チューニング用）
    if not scored_a and all_scored:
        all_scored.sort(key=lambda x: x.relevance_score, reverse=True)
        top5 = all_scored[:5]
        for i, sa in enumerate(top5):
            logger.info(
                "Stage A near-miss #%d: score=%.1f title='%s'",
                i + 1, sa.relevance_score, sa.article.title[:80],
            )

    # ── Stage A=0件 → フォールバック（sklearn有無に関わらず）──
    # score>0の上位K件を返す。run_daily側のmax_articles_per_runが最終コストガード。
    if not scored_a:
        if not all_scored:
            return []
        all_scored.sort(key=lambda x: x.relevance_score, reverse=True)
        fallback = [sa for sa in all_scored if sa.relevance_score > 0][:max(1, int(stage_b_top_k))]
        logger.info(
            "Stage A=0, fallback: returning top %d articles (score>0)",
            len(fallback),
        )
        return fallback

    # ── sklearn無し → Stage Aの結果をスコア降順で返す ──
    if not _HAS_SKLEARN:
        scored_a.sort(key=lambda x: x.relevance_score, reverse=True)
        logger.info("Stage B skipped (no sklearn). Returning %d Stage A articles", len(scored_a))
        return scored_a

    # ── Stage B: TF-IDF cosine similarity ──
    docs = [f"{sa.article.title}\n{sa.article.body}" for sa in scored_a]
    query = " ".join(list(keywords.keys())[:200])  # 念のため上限
    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform(docs + [query])
    sims = cosine_similarity(X[-1], X[:-1]).flatten()

    # TF-IDF類似度で上書きして降順ソート
    rescored = [
        ScoredArticle(article=scored_a[i].article, relevance_score=float(sims[i]))
        for i in range(len(scored_a))
    ]
    rescored.sort(key=lambda x: x.relevance_score, reverse=True)
    result = rescored[: max(1, int(stage_b_top_k))]

    # ── Stage B観測ログ ──
    logger.info(
        "Prefilter Stage B: %d → %d articles (top_k=%d)",
        len(scored_a), len(result), stage_b_top_k,
    )
    for i, sa in enumerate(result):
        logger.debug(
            "Stage B rank=%d: tfidf=%.4f title='%s'",
            i + 1, sa.relevance_score, sa.article.title[:80],
        )
    if len(rescored) > len(result):
        cutoff_score = result[-1].relevance_score if result else 0.0
        logger.debug(
            "Stage B cutoff: tfidf=%.4f (%d articles below cutoff)",
            cutoff_score, len(rescored) - len(result),
        )

    return result
