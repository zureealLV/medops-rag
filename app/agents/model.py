"""OpenAI-compatible provider with bounded retry and offline fallback."""

from __future__ import annotations

import re
import time

import httpx

from app.agents.rag import build_messages
from app.config import Settings
from app.models.artifacts import VisualEvidence
from app.models.retrieval import Evidence
from app.retrieval.embeddings import tokenize


def _extractive_answer(question: str, evidence: list[Evidence]) -> str:
    if not evidence:
        return ""
    structured = re.search(
        r"## 数据集答案\s*(.+?)(?=\n\s*## |\Z)", evidence[0].text, flags=re.DOTALL
    )
    if structured:
        answer = " ".join(structured.group(1).split())
        if answer:
            return f"{answer[:800]} [source:1]"
    query_tokens = set(tokenize(question))
    candidates: list[tuple[int, str, Evidence]] = []
    for item in evidence[:3]:
        for sentence in re.split(r"(?<=[。！？.!?])\s*|\n+", item.text):
            sentence = sentence.strip(" #-\t")
            if len(sentence) < 8:
                continue
            # Source pages often contain FAQ headings. Repeating a matched
            # question is not an answer, even when its lexical overlap is high.
            if sentence.endswith(("?", "？")):
                continue
            if sentence.lower().startswith(
                (
                    "source:",
                    "topic url:",
                    "bulk feed generated:",
                    "safety:",
                    "数据集：",
                    "hugging face 仓库：",
                    "固定版本：",
                    "原始文件：",
                    "许可证标记：",
                    "证据说明：",
                    "安全说明：",
                )
            ):
                continue
            overlap = len(query_tokens.intersection(tokenize(sentence)))
            candidates.append((overlap, sentence, item))
    candidates.sort(key=lambda value: value[0], reverse=True)
    selected = candidates[:2] or [(0, evidence[0].text[:240], evidence[0])]
    source_numbers = {
        (item.document_id, item.chunk_id): index for index, item in enumerate(evidence, start=1)
    }
    return " ".join(
        f"{sentence} [source:{source_numbers[(item.document_id, item.chunk_id)]}]"
        for _, sentence, item in selected
    )


def _offline_answer(
    question: str,
    evidence: list[Evidence],
    visual_payloads: list[tuple[VisualEvidence, bytes]],
) -> tuple[str, str, int]:
    answer = _extractive_answer(question, evidence)
    if visual_payloads:
        visual = visual_payloads[0][0]
        locator = (
            f"与问题最匹配的视觉证据来自 {visual.source} [image:1]。"
            "当前未启用视觉生成模型，不能据图推断未被检索证据明确支持的细节。"
        )
        answer = f"{answer} {locator}".strip()
        provider = "offline-extractive+visual-locator" if evidence else "offline-visual-locator"
    else:
        provider = "offline-extractive"
    tokens = len(
        tokenize(
            question
            + answer
            + " ".join(item.text for item in evidence)
            + " ".join(item.ocr_text for item, _ in visual_payloads)
        )
    )
    return answer, provider, tokens


def generate(
    question: str,
    evidence: list[Evidence],
    settings: Settings,
    visual_payloads: list[tuple[VisualEvidence, bytes]] | None = None,
) -> tuple[str, str, float, int]:
    started = time.perf_counter()
    visual_payloads = visual_payloads or []
    if not (settings.model_api_key and settings.model_base_url and settings.model_name):
        answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
        return answer, provider, 0.0, tokens

    if visual_payloads and not settings.model_vision_enabled:
        answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
        return answer, provider, 0.0, tokens

    endpoint = settings.model_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.model_name,
        "messages": build_messages(
            question,
            evidence,
            visual_payloads if settings.model_vision_enabled else None,
        ),
        "temperature": 0,
    }
    for attempt in range(settings.model_max_retries + 1):
        try:
            response = httpx.post(
                endpoint,
                headers={"Authorization": f"Bearer {settings.model_api_key}"},
                json=payload,
                timeout=settings.model_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            tokens = int(body.get("usage", {}).get("total_tokens", 0))
            return str(content), "openai-compatible", (time.perf_counter() - started) * 1000, tokens
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            if attempt < settings.model_max_retries:
                time.sleep(0.1 * (attempt + 1))
    answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
    fallback_provider = "offline-visual-fallback" if visual_payloads else "offline-fallback"
    if provider == "offline-extractive+visual-locator":
        fallback_provider = "offline-text+visual-fallback"
    return answer, fallback_provider, (time.perf_counter() - started) * 1000, tokens
