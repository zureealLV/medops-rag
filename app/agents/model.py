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
    category_list_question = bool(re.search(r"哪三类|分为.*类|几类", question))
    quantity_question = bool(re.search(r"多少|几(?:种|类|项)?", question))
    candidates: list[tuple[int, int, str, Evidence, list[str]]] = []
    for item in evidence[:3]:
        sentences = re.split(r"(?<=[。！？；.!?;])\s*|\n+", item.text)
        for sentence_index, sentence in enumerate(sentences):
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
                    "发布机构：",
                    "发布日期：",
                    "资料类别：",
                    "官方原文：",
                    "固定文件 sha-256：",
                    "来源等级：",
                )
            ):
                continue
            overlap = len(query_tokens.intersection(tokenize(sentence)))
            intent_bonus = 0
            if re.search(r"多少|几(?:种|类|项)?|哪(?:些|三类)", question):
                if re.search(r"\d|[一二三四五六七八九十]+类|(?:mg|kg|g|ml|%)", sentence, re.I):
                    intent_bonus += 2
            if category_list_question:
                if re.search(r"分类管理|分为[^。]{0,20}类", sentence):
                    intent_bonus += 10
                elif re.search(r"第[一二三]类", sentence):
                    intent_bonus += 4
            candidates.append((overlap + intent_bonus, sentence_index, sentence, item, sentences))
    candidates.sort(key=lambda value: value[0], reverse=True)
    selected: list[tuple[str, Evidence]] = []
    if candidates:
        _, sentence_index, sentence, item, sentences = candidates[0]
        selected.append((sentence, item))
        if category_list_question:
            for neighbor in sentences[sentence_index + 1 : sentence_index + 5]:
                neighbor = neighbor.strip(" #-\t")
                if re.search(r"第[一二三]类", neighbor):
                    selected.append((neighbor, item))
        if not category_list_question:
            quantity_concepts = [
                concept for concept in ("烹调油", "食盐") if concept in question
            ]
            if len(quantity_concepts) > 1:
                for concept in quantity_concepts:
                    match = next(
                        (
                            (candidate, candidate_item)
                            for _, _, candidate, candidate_item, _ in candidates
                            if concept in candidate and re.search(r"\d", candidate)
                        ),
                        None,
                    )
                    if match is not None and match not in selected:
                        selected.append(match)
            target_count = 1 if quantity_question else 2
            for _, _, candidate, candidate_item, _ in candidates[1:]:
                if len(selected) >= max(target_count, len(quantity_concepts)):
                    break
                if candidate not in {text for text, _ in selected}:
                    selected.append((candidate, candidate_item))
    if not selected:
        selected = [(evidence[0].text[:240], evidence[0])]
    source_numbers = {
        (item.document_id, item.chunk_id): index for index, item in enumerate(evidence, start=1)
    }
    return " ".join(
        f"{sentence} [source:{source_numbers[(item.document_id, item.chunk_id)]}]"
        for sentence, item in selected
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
