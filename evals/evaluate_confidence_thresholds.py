"""Evaluate absolute text-confidence floors on the frozen V2 retrieval set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from app.retrieval.embeddings import tokenize
from app.retrieval.keyword import keyword_score

ROOT = Path(__file__).resolve().parents[1]
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def normalized(values) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def descending(values: list[float]) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (-values[index], index))


def ranks(values: list[float]) -> list[int]:
    output = [0] * len(values)
    for rank, index in enumerate(descending(values), start=1):
        output[index] = rank
    return output


def gate_report(decisions: list[bool], expected: list[bool]) -> dict[str, float | int]:
    positives = sum(expected)
    negatives = len(expected) - positives
    accepted = sum(decision and wanted for decision, wanted in zip(decisions, expected, strict=True))
    abstained = sum(
        not decision and not wanted for decision, wanted in zip(decisions, expected, strict=True)
    )
    return {
        "answerable_accepted": accepted,
        "answerable_total": positives,
        "answerable_accept_rate": round(accepted / positives, 4),
        "negative_abstained": abstained,
        "negative_total": negatives,
        "negative_abstain_rate": round(abstained / negatives, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword-threshold", type=float, default=0.28)
    parser.add_argument("--dense-threshold", type=float, default=0.40)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/confidence-calibration-v2.json")
    args = parser.parse_args()

    documents = [
        json.loads(line)
        for line in (ROOT / "evals/v2_retrieval_documents.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/v2_retrieval_cases.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    texts = [document["text"] for document in documents]
    bm25 = BM25Okapi([tokenize(text) for text in texts])
    model = TextEmbedding(model_name=MODEL, cache_dir=str(ROOT / "data/models/fastembed"))
    document_vectors = [normalized(vector) for vector in model.embed(texts)]
    query_vectors = list(model.query_embed([case["question"] for case in cases]))

    bm25_decisions: list[bool] = []
    rrf_decisions: list[bool] = []
    expected = [not case["expected_abstain"] for case in cases]
    samples: list[dict[str, object]] = []
    for case, query_vector in zip(cases, query_vectors, strict=True):
        bm25_scores = [float(value) for value in bm25.get_scores(tokenize(case["question"]))]
        dense_scores = [
            float(np.dot(normalized(query_vector), document_vector))
            for document_vector in document_vectors
        ]
        keyword_scores = [keyword_score(case["question"], text) for text in texts]
        bm25_top = descending(bm25_scores)[0]
        bm25_accept = keyword_scores[bm25_top] >= args.keyword_threshold
        bm25_decisions.append(bm25_accept)

        bm25_ranks = ranks(bm25_scores)
        dense_ranks = ranks(dense_scores)
        rrf_scores = [
            1 / (60 + sparse_rank) + 1 / (60 + dense_rank)
            for sparse_rank, dense_rank in zip(bm25_ranks, dense_ranks, strict=True)
        ]
        rrf_top = descending(rrf_scores)[0]
        rrf_accept = (
            keyword_scores[rrf_top] >= args.keyword_threshold
            or dense_scores[rrf_top] >= args.dense_threshold
        )
        rrf_decisions.append(rrf_accept)
        if case["expected_abstain"] or not (bm25_accept and rrf_accept):
            samples.append(
                {
                    "id": case["id"],
                    "expected_answerable": not case["expected_abstain"],
                    "bm25_keyword_score": round(keyword_scores[bm25_top], 6),
                    "rrf_keyword_score": round(keyword_scores[rrf_top], 6),
                    "rrf_dense_score": round(dense_scores[rrf_top], 6),
                    "bm25_accepted": bm25_accept,
                    "rrf_accepted": rrf_accept,
                }
            )

    report = {
        "status": "pass",
        "dataset": "medops-v2-retrieval-frozen-v1",
        "cases": len(cases),
        "answerable": sum(expected),
        "negative": len(expected) - sum(expected),
        "thresholds": {
            "keyword": args.keyword_threshold,
            "dense_cosine": args.dense_threshold,
        },
        "model": MODEL,
        "gates": {
            "bm25": gate_report(bm25_decisions, expected),
            "rrf": gate_report(rrf_decisions, expected),
        },
        "samples": samples,
        "limitations": [
            "Synthetic frozen corpus; thresholds require recalibration for a new domain.",
            "This measures evidence admission, not generated-answer correctness.",
        ],
    }
    if any(
        gate[metric] < 1.0
        for gate in report["gates"].values()
        for metric in ("answerable_accept_rate", "negative_abstain_rate")
    ):
        report["status"] = "fail"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
