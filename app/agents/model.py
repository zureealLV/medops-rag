"""OpenAI-compatible provider with bounded retry and offline fallback."""

from __future__ import annotations

import re
import time

import httpx

from app.agents.rag import build_messages
from app.config import Settings
from app.models.retrieval import Evidence
from app.retrieval.embeddings import tokenize


def _extractive_answer(question: str, evidence: list[Evidence]) -> str:
    query_tokens = set(tokenize(question))
    candidates: list[tuple[int, str, Evidence]] = []
    for item in evidence[:3]:
        for sentence in re.split(r"(?<=[。！？.!?])\s*|\n+", item.text):
            sentence = sentence.strip(" #-\t")
            if len(sentence) < 8:
                continue
            overlap = len(query_tokens.intersection(tokenize(sentence)))
            candidates.append((overlap, sentence, item))
    candidates.sort(key=lambda value: value[0], reverse=True)
    selected = candidates[:2] or [(0, evidence[0].text[:240], evidence[0])]
    return " ".join(f"{sentence} [{item.document_id}:{item.chunk_id}]" for _, sentence, item in selected)


def generate(question: str, evidence: list[Evidence], settings: Settings) -> tuple[str, str, float, int]:
    started = time.perf_counter()
    if not (settings.model_api_key and settings.model_base_url and settings.model_name):
        answer = _extractive_answer(question, evidence)
        tokens = len(tokenize(question + answer + " ".join(item.text for item in evidence)))
        return answer, "offline-extractive", 0.0, tokens

    endpoint = settings.model_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.model_name,
        "messages": build_messages(question, evidence),
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
    answer = _extractive_answer(question, evidence)
    tokens = len(tokenize(question + answer + " ".join(item.text for item in evidence)))
    return answer, "offline-fallback", (time.perf_counter() - started) * 1000, tokens
