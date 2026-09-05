"""Run deterministic retrieval, citation, and abstention evaluation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.config import Settings
from app.models.answers import AnswerRequest
from app.services.answers import answer
from scripts.seed_sample_data import seed

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    with tempfile.TemporaryDirectory(prefix="medops-eval-") as directory:
        settings = Settings(database_path=Path(directory) / "eval.db")
        kb_id, _ = seed(settings)
        failures: list[dict[str, object]] = []
        retrieval_hits = citation_hits = abstention_hits = 0
        answerable = sum(not case["expected_abstain"] for case in cases)
        abstainable = len(cases) - answerable
        for case in cases:
            result = answer(
                settings.database_path,
                settings,
                "hospital-a",
                AnswerRequest(question=case["question"], knowledge_base_id=kb_id),
            )
            assert result is not None
            sources = [item.source for item in result.retrieved_chunks[:5]]
            citations = [item.source for item in result.citations]
            if case["expected_abstain"]:
                abstention_hits += int(result.abstained)
                passed = result.abstained
            else:
                retrieval_hits += int(case["expected_source"] in sources)
                citation_hits += int(case["expected_source"] in citations)
                passed = (
                    case["expected_source"] in sources
                    and case["expected_source"] in citations
                    and not result.abstained
                )
            if not passed:
                failures.append(
                    {
                        "question": case["question"],
                        "expected_source": case["expected_source"],
                        "sources": sources,
                        "abstained": result.abstained,
                    }
                )

    report = {
        "cases": len(cases),
        "answerable": answerable,
        "retrieval_hit_at_5": round(retrieval_hits / answerable, 4),
        "citation_correctness": round(citation_hits / answerable, 4),
        "correct_abstention": round(abstention_hits / abstainable, 4),
        "failures": failures,
    }
    output = ROOT / "reports" / "generated" / "evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
