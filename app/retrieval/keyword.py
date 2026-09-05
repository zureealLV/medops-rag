"""Token-overlap keyword scoring."""

from __future__ import annotations

from collections import Counter

from app.retrieval.embeddings import tokenize


def keyword_score(query: str, text: str) -> float:
    query_tokens = Counter(tokenize(query))
    text_tokens = Counter(tokenize(text))
    if not query_tokens:
        return 0.0
    matched = sum(min(count, text_tokens[token]) for token, count in query_tokens.items())
    return matched / sum(query_tokens.values())
