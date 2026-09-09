"""Compare chunk profiles on the hash-pinned Chinese government PDF corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import Settings
from scripts.import_chinese_official import DEFAULT_CATALOG, DEFAULT_OUTPUT, load_catalog, parse_official_pdf

try:
    from evals.benchmark_chunk_profiles import evaluate
except ModuleNotFoundError:  # Direct `python evals/...py` execution.
    from benchmark_chunk_profiles import evaluate

ROOT = Path(__file__).resolve().parents[1]
PROFILES = (
    "enterpriseqa_fixed_500_50",
    "medops_semantic_500_50",
    "medops_semantic_600_80",
    "medops_parent_child_1600_350_50",
)


def _load_cases(catalog_path: Path) -> tuple[tuple[str, str, str], ...]:
    sources = load_catalog(catalog_path)
    raw_cases = [
        json.loads(line)
        for line in (ROOT / "evals/chinese_official_cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    cases: list[tuple[str, str, str]] = []
    for case in raw_cases:
        if case["expected_abstain"]:
            continue
        source = next(
            (
                item.url
                for item in sources
                if case["expected_source_contains"] in item.url
            ),
            None,
        )
        if source is None:
            raise ValueError(f"No catalog source matches case {case['id']}")
        cases.append((case["question"], source, case["expected_answer_contains"]))
    return tuple(cases)


def _load_documents(catalog_path: Path, source_dir: Path) -> dict[str, str]:
    settings = Settings.from_env()
    documents: dict[str, str] = {}
    for source in load_catalog(catalog_path):
        path = source_dir / "raw" / source.filename
        if not path.is_file():
            raise SystemExit(f"Official source file is missing: {path}")
        documents[source.url] = parse_official_pdf(source, path.read_bytes(), settings).content
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/chunk-profile-official-v3.json",
    )
    args = parser.parse_args()

    catalog_path = args.catalog.resolve()
    documents = _load_documents(catalog_path, args.source_dir.resolve())
    cases = _load_cases(catalog_path)
    results: dict[str, Any] = {
        name: evaluate(name, documents, cases) for name in PROFILES
    }
    report = {
        "benchmark": "medops-official-chunk-profiles-v3",
        "corpus": "data/external/chinese_official/raw (hash-pinned; binaries ignored by Git)",
        "documents": len(documents),
        "source_characters": sum(len(text) for text in documents.values()),
        "questions": len(cases),
        "retriever": "rank-bm25 0.2.2 with identical tokenizer and top-1 selection",
        "results": results,
        "limitations": [
            "The six answerable questions are a small labelled set, so quality differences need "
            "confirmation on a larger held-out corpus.",
            "PDF extraction is performed once before timing; index_build_ms measures chunk planning only.",
            "Fixed 500/50 is a local EnterpriseQA-style reference, not LangChain's exact splitter.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
