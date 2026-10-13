"""Pure ranking helpers: keyword queries, reciprocal rank fusion, aggregation and CPC voting."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

STOPWORDS = frozenset(
    """
    about above after again against also among and any are because been before being below
    between both but can could did does doing down during each either else from further had has
    have having here how into its itself just like may might more most must not now once only other
    our out over own same should some such than that the their them then there these they this
    those through under until upon very was were what when where which while who whom why will
    with within without would you your said wherein thereof therein comprising comprises include
    includes included including use used using based one two first second plurality least
    """.split()
)

_TOKEN = re.compile(r"[a-z][a-z0-9-]{3,}")


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """Most frequent non-stopword terms, longer terms first on ties. Deterministic."""
    counts = Counter(t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS)
    ranked = sorted(counts, key=lambda term: (-counts[term], -len(term), term))
    return ranked[:limit]


def build_or_query(text: str, limit: int = 12) -> str:
    """websearch_to_tsquery syntax that ORs the key terms, empty when there are none.

    websearch_to_tsquery ANDs plain words, which returns nothing for a long disclosure, so the
    terms are joined with the `or` operator it understands.
    """
    return " or ".join(extract_keywords(text, limit))


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to an id, ranks start at 1."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] += 1.0 / (k + rank)
    return dict(scores)


@dataclass(frozen=True)
class PatentScore:
    patent_id: str
    score: float
    chunk_ids: list[str]  # best chunks first


def aggregate_by_patent(
    chunk_scores: dict[str, float], chunk_patent: dict[str, str], top_chunks: int = 3
) -> list[PatentScore]:
    """Patent score = best chunk score + mean of its top `top_chunks` chunk scores."""
    grouped: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for chunk_id, score in chunk_scores.items():
        grouped[chunk_patent[chunk_id]].append((score, chunk_id))
    results: list[PatentScore] = []
    for patent_id, items in grouped.items():
        items.sort(key=lambda pair: (-pair[0], pair[1]))
        best = items[:top_chunks]
        score = best[0][0] + sum(s for s, _ in best) / len(best)
        results.append(PatentScore(patent_id, score, [chunk_id for _, chunk_id in best]))
    results.sort(key=lambda r: (-r.score, r.patent_id))
    return results


def vote_cpc(
    ranked_subclasses: Sequence[Sequence[str]], depth: int = 30, top: int = 5
) -> list[tuple[str, int]]:
    """Each of the first `depth` patents votes once for each of its CPC subclasses.

    Ties go to the subclass that appears in a better ranked patent first.
    """
    votes: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for position, subclasses in enumerate(ranked_subclasses[:depth]):
        for subclass in dict.fromkeys(subclasses):
            if not subclass:
                continue
            votes[subclass] += 1
            first_seen.setdefault(subclass, position)
    ordered = sorted(votes, key=lambda s: (-votes[s], first_seen[s], s))
    return [(subclass, votes[subclass]) for subclass in ordered[:top]]


def like_prefix(prefix: str) -> str:
    """Escape LIKE wildcards in a user-supplied CPC prefix and append the trailing wildcard."""
    cleaned = prefix.strip().upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return cleaned + "%"
