"""Vector score helpers."""

from app.retrieval.embeddings import cosine


def vector_score(query_vector: list[float], chunk_vector: list[float]) -> float:
    # Hashing vectors may be weakly negative; retrieval scores are easier to reason
    # about when non-matches have a floor of zero.
    return max(0.0, cosine(query_vector, chunk_vector))
