"""Exercise the real HTTP conversation API with colloquial multi-turn Chinese."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.knowledge_bases import list_all
from scripts.import_chinese_official import KB_NAME

ROOT = Path(__file__).resolve().parents[1]


def read_dotenv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            result[name.strip()] = value.strip().strip('"').strip("'")
    return result


def normalized(value: str) -> str:
    return re.sub(r"[\s，。、：；,.!?！？*#_()（）]+", "", value).replace("克", "g").lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--database", type=Path, default=ROOT / "data/runtime/medops.db")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/conversation-live-v1.json")
    args = parser.parse_args()
    key = (
        os.getenv("MODEL_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or read_dotenv(args.env_file).get("DEEPSEEK_API_KEY", "")
    )
    if not key:
        raise SystemExit("DeepSeek API key is required")
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/conversational_colloquial_cases_zh.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="medops-conversation-eval-") as temp:
        database = Path(temp) / "eval.db"
        shutil.copy2(args.database, database)
        settings = replace(
            Settings.from_env(),
            database_path=database,
            model_api_key=key,
            model_base_url="https://api.deepseek.com",
            model_name="deepseek-v4-flash",
            policy_profile="medical",
            auth_mode="trusted_headers",
        )
        kb = next((item for item in list_all(database, "hospital-a") if item.name == KB_NAME), None)
        if kb is None:
            raise SystemExit("Official Chinese corpus is missing")
        headers = {"X-Tenant-ID": "hospital-a", "X-Actor-ID": "colloquial-evaluator"}
        with TestClient(create_app(settings)) as client:
            for repetition in range(args.repetitions):
                for case in cases:
                    created = client.post(
                        "/conversations", headers=headers, json={"knowledge_base_id": kb.id}
                    )
                    created.raise_for_status()
                    conversation_id = created.json()["id"]
                    for turn_index, turn in enumerate(case["turns"], 1):
                        started = time.perf_counter()
                        response = client.post(
                            f"/conversations/{conversation_id}/messages",
                            headers=headers,
                            json={"content": turn["content"]},
                            timeout=120,
                        )
                        latency = (time.perf_counter() - started) * 1000
                        response.raise_for_status()
                        payload = response.json()
                        answer = payload["answer"]
                        sources = [item["source"] for item in answer["citations"]]
                        abstain_ok = bool(answer["abstained"]) == bool(turn.get("abstain", False))
                        reason_ok = not turn.get("reason") or answer["reason"] == turn["reason"]
                        source_ok = not turn.get("source_contains") or any(
                            turn["source_contains"] in source for source in sources
                        )
                        content_ok = not turn.get("answer_contains") or normalized(
                            turn["answer_contains"]
                        ) in normalized(answer["answer"])
                        context_ok = turn_index == 1 or normalized(
                            payload["contextualized_question"]
                        ) != normalized(turn["content"])
                        passed = abstain_ok and reason_ok and source_ok and content_ok and context_ok
                        rows.append(
                            {
                                "repetition": repetition + 1,
                                "case": case["id"],
                                "turn": turn_index,
                                "input": turn["content"],
                                "expected_abstain": bool(turn.get("abstain", False)),
                                "expects_source": bool(turn.get("source_contains")),
                                "expects_content": bool(turn.get("answer_contains")),
                                "contextualized_question": payload["contextualized_question"],
                                "passed": passed,
                                "abstain_ok": abstain_ok,
                                "reason_ok": reason_ok,
                                "source_ok": source_ok,
                                "content_ok": content_ok,
                                "context_ok": context_ok,
                                "abstained": answer["abstained"],
                                "reason": answer["reason"],
                                "provider": answer["provider"],
                                "orchestration": answer["orchestration"],
                                "citations": sources,
                                "answer": answer["answer"],
                                "latency_ms": round(latency, 3),
                                "model_ms": answer["model_ms"],
                                "retrieval_ms": answer["retrieval_ms"],
                                "token_usage": answer["token_usage"],
                            }
                        )
    latencies = [float(row["latency_ms"]) for row in rows]
    citation_rows = [row for row in rows if row["expects_source"]]
    content_rows = [row for row in rows if row["expects_content"]]
    safety_rows = [row for row in rows if row["expected_abstain"]]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "deepseek-v4-flash",
        "transport": "FastAPI TestClient against POST /conversations/{id}/messages",
        "repetitions": args.repetitions,
        "conversations": len(cases) * args.repetitions,
        "turns": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "accuracy": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "context_resolution_accuracy": round(sum(bool(row["context_ok"]) for row in rows) / len(rows), 4),
        "citation_accuracy": round(
            sum(bool(row["source_ok"]) for row in citation_rows) / len(citation_rows), 4
        ),
        "content_accuracy": round(
            sum(bool(row["content_ok"]) for row in content_rows) / len(content_rows), 4
        ),
        "safety_accuracy": round(
            sum(bool(row["abstain_ok"]) and bool(row["reason_ok"]) for row in safety_rows) / len(safety_rows),
            4,
        ),
        "live_provider_turns": sum(row["provider"] == "openai-compatible" for row in rows),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "total_tokens": sum(int(row["token_usage"]) for row in rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
