from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from .models import Article

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
    stage_a_threshold: float = 6.0,
    stage_b_top_k: int = 30,
) -> List[ScoredArticle]:
    """Spec M1:
    - Stage A: keyword weighted score, threshold >= 6.0
    - Stage B: TF-IDF cosine similarity, top_k only (if sklearn available)
    """
    scored_a: List[ScoredArticle] = []
    for a in articles:
        text = f"{a.title}\n{a.body}"
        s = _kw_score(text, keywords)
        if s >= stage_a_threshold:
            scored_a.append(ScoredArticle(article=a, relevance_score=s))

    if not _HAS_SKLEARN:
        return scored_a

    if not scored_a:
        return []

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
    return rescored[: max(1, int(stage_b_top_k))]
