"""Frozen V2 retrieval benchmark: lexical, multilingual dense, fusion and reranking."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder.text_cross_encoder import TextCrossEncoder
from rank_bm25 import BM25Okapi

from app.retrieval.embeddings import tokenize

ROOT = Path(__file__).resolve().parents[1]
DENSE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANK = "BAAI/bge-reranker-base"


def norm(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def order(v):
    return sorted(range(len(v)), key=lambda i: (-v[i], i))


def ranks(v):
    out = [0] * len(v)
    for r, i in enumerate(order(v), 1):
        out[i] = r
    return out


def metrics(rankings, cases, latencies):
    rr = []
    ndcg = []
    hits = {1: 0, 3: 0, 5: 0}
    groups = {}
    for ranking, c in zip(rankings, cases, strict=True):
        rank = next((i for i, s in enumerate(ranking, 1) if s == c["expected_source"]), None)
        rr.append(1 / rank if rank else 0)
        ndcg.append(1 / np.log2(rank + 1) if rank else 0)
        for k in hits:
            hits[k] += int(rank is not None and rank <= k)
        groups.setdefault(c["category"], []).append(int(rank == 1))
    n = len(cases)
    so = sorted(latencies)
    return {
        "hit_at_1": round(hits[1] / n, 4),
        "hit_at_3": round(hits[3] / n, 4),
        "hit_at_5": round(hits[5] / n, 4),
        "mrr_at_5": round(statistics.fmean(rr), 4),
        "ndcg_at_5": round(statistics.fmean(ndcg), 4),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "p95_ms": round(so[int(0.95 * (len(so) - 1))], 3),
        "hit_at_1_by_category": {k: round(sum(v) / len(v), 4) for k, v in groups.items()},
    }


def main():
    dp = ROOT / "evals/v2_retrieval_documents.jsonl"
    cp = ROOT / "evals/v2_retrieval_cases.jsonl"
    docs = [json.loads(x) for x in dp.read_text(encoding="utf-8").splitlines()]
    all_cases = [json.loads(x) for x in cp.read_text(encoding="utf-8").splitlines()]
    cases = [x for x in all_cases if not x["expected_abstain"]]
    negatives = [x for x in all_cases if x["expected_abstain"]]
    texts = [x["text"] for x in docs]
    sources = [x["source"] for x in docs]
    bm = BM25Okapi([tokenize(x) for x in texts])
    cache = str(ROOT / "data/models/fastembed")
    t = time.perf_counter()
    dense = TextEmbedding(model_name=DENSE, cache_dir=cache)
    dense_load = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    reranker = TextCrossEncoder(model_name=RERANK, cache_dir=cache)
    rerank_load = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    vectors = [norm(v) for v in dense.embed(texts)]
    index_ms = (time.perf_counter() - t) * 1000
    names = ["bm25", "minilm", "rrf", "rrf_bge"]
    rankings = {n: [] for n in names}
    times = {n: [] for n in names}
    negative_max = {n: [] for n in ["bm25", "minilm", "rrf"]}

    def score(q, with_rerank=True):
        t = time.perf_counter()
        bs = [float(x) for x in bm.get_scores(tokenize(q))]
        bo = order(bs)
        bt = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        qv = norm(next(dense.query_embed(q)))
        ds = [float(np.dot(qv, v)) for v in vectors]
        do = order(ds)
        dt = (time.perf_counter() - t) * 1000
        br = ranks(bs)
        dr = ranks(ds)
        fs = [1 / (60 + a) + 1 / (60 + b) for a, b in zip(br, dr, strict=True)]
        fo = order(fs)
        ro = []
        rt = 0
        if with_rerank:
            t = time.perf_counter()
            cand = fo[:10]
            rs = list(reranker.rerank(q, [texts[i] for i in cand]))
            ro = [cand[i] for i in order(rs)]
            rt = (time.perf_counter() - t) * 1000
        return bs, ds, fs, bo, do, fo, ro, bt, dt, rt

    for c in cases:
        bs, ds, fs, bo, do, fo, ro, bt, dt, rt = score(c["question"])
        for n, o, tm in [
            ("bm25", bo, bt),
            ("minilm", do, dt),
            ("rrf", fo, bt + dt),
            ("rrf_bge", ro, bt + dt + rt),
        ]:
            rankings[n].append([sources[i] for i in o[:5]])
            times[n].append(tm)
    for c in negatives:
        bs, ds, fs, *_ = score(c["question"], False)
        negative_max["bm25"].append(max(bs))
        negative_max["minilm"].append(max(ds))
        negative_max["rrf"].append(max(fs))
    report = {
        "benchmark": "medops-v2-retrieval-frozen-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "documents": len(docs),
        "answerable_questions": len(cases),
        "negative_questions": len(negatives),
        "dataset_sha256": {
            dp.name: hashlib.sha256(dp.read_bytes()).hexdigest(),
            cp.name: hashlib.sha256(cp.read_bytes()).hexdigest(),
        },
        "models": {
            "dense": DENSE,
            "reranker": RERANK,
            "dense_load_ms": round(dense_load, 3),
            "reranker_load_ms": round(rerank_load, 3),
            "dense_index_ms": round(index_ms, 3),
        },
        "results": {n: metrics(rankings[n], cases, times[n]) for n in names},
        "negative_max_scores": {
            n: {"mean": round(statistics.fmean(v), 6), "max": round(max(v), 6)}
            for n, v in negative_max.items()
        },
        "limitations": [
            "Template-generated synthetic operations corpus; not production traffic.",
            "Model files cached; download time excluded.",
            "One relevant document per answerable query.",
        ],
    }
    out = ROOT / "reports/retrieval-benchmark-v2-beta1.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
