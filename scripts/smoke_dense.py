"""Real FastEmbed dense indexing/query smoke test."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.db import initialize
from app.models.documents import DocumentCreate
from app.models.knowledge_bases import KnowledgeBaseCreate
from app.models.retrieval import SearchRequest
from app.services import documents, knowledge_bases
from app.services.retrieval import search


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="medops-dense-") as directory:
        path = Path(directory) / "dense.db"
        settings = Settings(database_path=path, text_embedding_enabled=True)
        initialize(path)
        kb = knowledge_bases.create(path, "hospital-a", KnowledgeBaseCreate(name="Dense smoke"))
        started = time.perf_counter()
        fixtures = (
            ("cert", "网关证书即将过期时，应先生成变更单并轮换 TLS 凭据。"),
            ("disk", "归档存储容量不足时扩容磁盘并检查挂载点。"),
            ("queue", "接口消息堆积时检查消费者状态和死信队列。"),
        )
        for title, content in fixtures:
            documents.create(
                path,
                settings,
                "hospital-a",
                kb.id,
                DocumentCreate(title=title, source=f"{title}.md", content=content),
            )
        index_ms = (time.perf_counter() - started) * 1000
        result = search(
            path,
            "hospital-a",
            SearchRequest(query="如何更新 gateway credential？", strategy="vector", top_k=3),
            settings,
        )
        assert result is not None and result.results[0].source == "cert.md"
        report = {
            "model": settings.text_embedding_model,
            "documents": 3,
            "index_ms": round(index_ms, 3),
            "query_ms": result.retrieval_ms,
            "top_source": result.results[0].source,
            "top_cosine": result.results[0].score,
        }
        destination = Path("reports/smoke-v2-beta1-dense.json")
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
