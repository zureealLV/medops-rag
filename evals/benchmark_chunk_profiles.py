"""Compare EnterpriseQA-style fixed windows with MedOps semantic and parent-child chunks."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from app.ingestion.parsers import NormalizedElement
from app.retrieval.chunking import normalize_text, split_text
from app.retrieval.embeddings import tokenize
from app.retrieval.structure_chunking import build_parent_child_chunks

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "sample_data" / "medical_knowledge"
CASES = (
    ("哪些因素可能影响脉搏血氧仪读数？", "pulse_oximeter_basics.md", "末梢循环不佳"),
    ("输液泵常见风险包括什么？", "infusion_pump_safety.md", "软件缺陷"),
    ("Spaulding 风险分类包括哪三类？", "device_reprocessing.md", "关键、半关键和非关键"),
    ("医疗设备维护策略包括什么？", "equipment_maintenance_lifecycle.md", "检查、预防性维护和纠正性维护"),
    ("标准预防适用于哪些患者？", "standard_precautions.md", "适用于所有患者照护"),
    ("手卫生五个时刻包含什么？", "hand_hygiene_five_moments.md", "接触患者前"),
    ("四项常见生命体征是什么？", "vital_signs_overview.md", "体温、脉搏或心率、呼吸频率和血压"),
)


def fixed_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Reference baseline matching fixed character windows without semantic snapping."""
    normalized = normalize_text(text)
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = end - overlap
    return chunks


def ends_at_semantic_boundary(text: str) -> bool:
    return text.endswith(("。", "！", "？", "；", ".", "!", "?", ";")) or bool(
        re.search(r"(?:https?://\S+|访问日期：\d{4}-\d{2}-\d{2})$", text)
    )


def context_contains_expected(context: str, expected: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"[\s*#_，。、；：,.!！?？()（）\[\]【】]+", "", value).replace("克", "g").lower()

    normalized_context = normalize(context)
    normalized_expected = normalize(expected)
    if normalized_expected in normalized_context:
        return True
    terms = [normalize(term) for term in re.split(r"[、，,；;和]", expected) if normalize(term)]
    return len(terms) > 1 and all(term in normalized_context for term in terms)


def build_profile(name: str, documents: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source, text in documents.items():
        if name == "enterpriseqa_fixed_500_50":
            pairs = [(chunk, chunk) for chunk in fixed_chunks(text, 500, 50)]
        elif name == "medops_semantic_500_50":
            pairs = [(chunk, chunk) for chunk in split_text(text, size=500, overlap=50)]
        elif name == "medops_semantic_600_80":
            pairs = [(chunk, chunk) for chunk in split_text(text, size=600, overlap=80)]
        else:
            plans = build_parent_child_chunks(
                (NormalizedElement(modality="text", text=text),),
                parent_size=1600,
                child_size=350,
                child_overlap=50,
            )
            pairs = [(child, plan.text) for plan in plans for child in plan.children]
        items.extend(
            {
                "source": source,
                "retrieval_text": child,
                "answer_context": context,
                "terminal": index == len(pairs) - 1,
            }
            for index, (child, context) in enumerate(pairs)
        )
    return items


def evaluate(
    name: str,
    documents: dict[str, str],
    cases: tuple[tuple[str, str, str], ...] = CASES,
) -> dict[str, Any]:
    started = time.perf_counter()
    items = build_profile(name, documents)
    index_ms = (time.perf_counter() - started) * 1000
    bm25 = BM25Okapi([tokenize(item["retrieval_text"]) for item in items])
    hit_at_1 = hit_at_5 = context_complete = context_complete_at_5 = 0
    context_incomplete_at_1: list[str] = []
    latencies = []
    for question, expected_source, expected_text in cases:
        started = time.perf_counter()
        scores = bm25.get_scores(tokenize(question))
        ranked_indices = sorted(
            range(len(items)), key=lambda index: (-float(scores[index]), index)
        )
        top_index = ranked_indices[0]
        latencies.append((time.perf_counter() - started) * 1000)
        top = items[top_index]
        hit_at_1 += int(top["source"] == expected_source)
        top_complete = (
            top["source"] == expected_source
            and context_contains_expected(top["answer_context"], expected_text)
        )
        context_complete += int(top_complete)
        if not top_complete:
            context_incomplete_at_1.append(question)
        top_five = [items[index] for index in ranked_indices[:5]]
        hit_at_5 += int(any(item["source"] == expected_source for item in top_five))
        context_complete_at_5 += int(
            any(
                item["source"] == expected_source
                and context_contains_expected(item["answer_context"], expected_text)
                for item in top_five
            )
        )

    retrieval_chars = sum(len(item["retrieval_text"]) for item in items)
    source_chars = sum(len(normalize_text(text)) for text in documents.values())
    internal_chunks = [item["retrieval_text"] for item in items if not item["terminal"]]
    broken_boundaries = [
        text
        for text in internal_chunks
        if not ends_at_semantic_boundary(text)
    ]
    return {
        "chunks": len(items),
        "mean_chunk_chars": round(statistics.fmean(len(item["retrieval_text"]) for item in items), 3),
        "duplicated_character_ratio": round(max(0, retrieval_chars - source_chars) / source_chars, 4),
        "mid_sentence_boundary_ratio": round(
            len(broken_boundaries) / len(internal_chunks) if internal_chunks else 0.0,
            4,
        ),
        "bm25_hit_at_1": round(hit_at_1 / len(cases), 4),
        "bm25_hit_at_5": round(hit_at_5 / len(cases), 4),
        "answer_context_complete_at_1": round(context_complete / len(cases), 4),
        "answer_context_complete_at_5": round(context_complete_at_5 / len(cases), 4),
        "context_incomplete_at_1_questions": context_incomplete_at_1,
        "index_build_ms": round(index_ms, 3),
        "query_mean_ms": round(statistics.fmean(latencies), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "chunk-profile-benchmark-v3.json",
    )
    args = parser.parse_args()
    documents = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(CORPUS.rglob("*.md"))
    }
    profiles = (
        "enterpriseqa_fixed_500_50",
        "medops_semantic_500_50",
        "medops_semantic_600_80",
        "medops_parent_child_1600_350_50",
    )
    report = {
        "benchmark": "medops-chunk-profiles-v3",
        "corpus": "sample_data/medical_knowledge",
        "documents": len(documents),
        "questions": len(CASES),
        "results": {name: evaluate(name, documents) for name in profiles},
        "limitations": [
            "Seven concise educational documents make retrieval easy; context completeness "
            "and boundaries are the stronger diagnostics.",
            "BM25 is held constant; this benchmark does not compare embedding models.",
            "Fixed 500/50 is a local reference implementation of the EnterpriseQA policy, "
            "not LangChain's splitter implementation.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
