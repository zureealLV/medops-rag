"""OpenAI-compatible provider with bounded retry and offline fallback."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import httpx

from app.agents.rag import build_messages
from app.config import Settings
from app.models.artifacts import VisualEvidence
from app.models.retrieval import Evidence
from app.retrieval.embeddings import tokenize


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Provider token counters used by benchmarks and cost estimates."""

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GenerationResult:
    answer: str
    provider: str
    model_ms: float
    usage: ModelUsage


OverloadReason = Literal["queue_full", "queue_timeout"]


class ModelProviderOverloadedError(RuntimeError):
    """The bounded provider admission queue cannot accept this request."""

    def __init__(
        self,
        *,
        reason: OverloadReason,
        retry_after_seconds: int,
        max_concurrency: int,
        max_queue_waiters: int,
        waited_ms: float,
    ) -> None:
        super().__init__(f"model provider overloaded: {reason}")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        self.max_concurrency = max_concurrency
        self.max_queue_waiters = max_queue_waiters
        self.waited_ms = waited_ms


class ModelProvider:
    """Thread-safe, process-local provider client and bounded admission gate.

    A request holds its execution slot for the complete retry loop, including
    backoff. This prevents retries from escaping the configured Provider budget.
    The admission semaphore caps active plus waiting calls, while the execution
    semaphore caps calls that may reach the Provider concurrently.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if settings.model_max_concurrency < 1:
            raise ValueError("MODEL_MAX_CONCURRENCY must be at least 1")
        if settings.model_max_queue_waiters < 0:
            raise ValueError("MODEL_MAX_QUEUE_WAITERS cannot be negative")
        if settings.model_queue_timeout_seconds < 0:
            raise ValueError("MODEL_QUEUE_TIMEOUT_SECONDS cannot be negative")
        if settings.model_overload_retry_after_seconds < 1:
            raise ValueError("MODEL_OVERLOAD_RETRY_AFTER_SECONDS must be at least 1")

        self.max_concurrency = settings.model_max_concurrency
        self.max_queue_waiters = settings.model_max_queue_waiters
        self.queue_timeout_seconds = settings.model_queue_timeout_seconds
        self.retry_after_seconds = settings.model_overload_retry_after_seconds
        self._admission = threading.BoundedSemaphore(self.max_concurrency + self.max_queue_waiters)
        self._execution = threading.BoundedSemaphore(self.max_concurrency)
        self._client = httpx.Client(
            timeout=settings.model_timeout_seconds,
            limits=httpx.Limits(
                max_connections=self.max_concurrency,
                max_keepalive_connections=self.max_concurrency,
            ),
            transport=transport,
        )
        self._state_lock = threading.Lock()
        self._state_changed = threading.Condition(self._state_lock)
        self._closed = False
        self._active = 0
        self._admitted = 0

    @property
    def is_closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def capacity_snapshot(self) -> dict[str, int]:
        """Return lock-protected counters for diagnostics and deterministic tests."""
        with self._state_lock:
            return {
                "active": self._active,
                "waiting": max(0, self._admitted - self._active),
                "max_concurrency": self.max_concurrency,
                "max_queue_waiters": self.max_queue_waiters,
            }

    @contextmanager
    def request_slot(self):
        started = time.perf_counter()
        if not self._admission.acquire(blocking=False):
            raise self._overload("queue_full", started)
        with self._state_lock:
            if self._closed:
                self._admission.release()
                raise RuntimeError("model provider is closed")
            self._admitted += 1

        acquired_execution = False
        try:
            acquired_execution = self._execution.acquire(timeout=self.queue_timeout_seconds)
            if not acquired_execution:
                raise self._overload("queue_timeout", started)
            with self._state_lock:
                self._active += 1
            yield self._client
        finally:
            if acquired_execution:
                with self._state_lock:
                    self._active -= 1
                self._execution.release()
            with self._state_changed:
                self._admitted -= 1
                self._state_changed.notify_all()
            self._admission.release()

    def _overload(self, reason: OverloadReason, started: float) -> ModelProviderOverloadedError:
        return ModelProviderOverloadedError(
            reason=reason,
            retry_after_seconds=self.retry_after_seconds,
            max_concurrency=self.max_concurrency,
            max_queue_waiters=self.max_queue_waiters,
            waited_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def close(self) -> None:
        with self._state_changed:
            if self._closed:
                return
            self._closed = True
            self._state_changed.wait_for(lambda: self._admitted == 0)
        self._client.close()

    def __enter__(self) -> ModelProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _extractive_answer(question: str, evidence: list[Evidence]) -> str:
    if not evidence:
        return ""
    structured = re.search(r"## 数据集答案\s*(.+?)(?=\n\s*## |\Z)", evidence[0].text, flags=re.DOTALL)
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
            quantity_concepts = [concept for concept in ("烹调油", "食盐") if concept in question]
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


def generate_detailed(
    question: str,
    evidence: list[Evidence],
    settings: Settings,
    visual_payloads: list[tuple[VisualEvidence, bytes]] | None = None,
    provider: ModelProvider | None = None,
) -> GenerationResult:
    started = time.perf_counter()
    visual_payloads = visual_payloads or []
    if not (settings.model_api_key and settings.model_base_url and settings.model_name):
        answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
        completion_tokens = len(tokenize(answer))
        return GenerationResult(
            answer,
            provider,
            0.0,
            ModelUsage(
                total_tokens=tokens,
                prompt_tokens=max(0, tokens - completion_tokens),
                completion_tokens=completion_tokens,
            ),
        )

    if visual_payloads and not settings.model_vision_enabled:
        answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
        completion_tokens = len(tokenize(answer))
        return GenerationResult(
            answer,
            provider,
            0.0,
            ModelUsage(
                total_tokens=tokens,
                prompt_tokens=max(0, tokens - completion_tokens),
                completion_tokens=completion_tokens,
            ),
        )

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
    owns_provider = provider is None
    runtime = provider or ModelProvider(settings)
    try:
        with runtime.request_slot() as client:
            for attempt in range(settings.model_max_retries + 1):
                try:
                    response = client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {settings.model_api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage", {})
                    prompt_tokens = int(usage.get("prompt_tokens", 0))
                    completion_tokens = int(usage.get("completion_tokens", 0))
                    cached_prompt_tokens = int(
                        usage.get("prompt_cache_hit_tokens")
                        or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                        or 0
                    )
                    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
                    return GenerationResult(
                        str(content),
                        "openai-compatible",
                        (time.perf_counter() - started) * 1000,
                        ModelUsage(
                            total_tokens=total_tokens,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cached_prompt_tokens=cached_prompt_tokens,
                        ),
                    )
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
                    if attempt < settings.model_max_retries:
                        time.sleep(0.1 * (attempt + 1))
    finally:
        if owns_provider:
            runtime.close()
    answer, provider, tokens = _offline_answer(question, evidence, visual_payloads)
    fallback_provider = "offline-visual-fallback" if visual_payloads else "offline-fallback"
    if provider == "offline-extractive+visual-locator":
        fallback_provider = "offline-text+visual-fallback"
    completion_tokens = len(tokenize(answer))
    return GenerationResult(
        answer,
        fallback_provider,
        (time.perf_counter() - started) * 1000,
        ModelUsage(
            total_tokens=tokens,
            prompt_tokens=max(0, tokens - completion_tokens),
            completion_tokens=completion_tokens,
        ),
    )


def generate(
    question: str,
    evidence: list[Evidence],
    settings: Settings,
    visual_payloads: list[tuple[VisualEvidence, bytes]] | None = None,
    provider: ModelProvider | None = None,
) -> tuple[str, str, float, int]:
    """Compatibility wrapper for call sites that only need total token usage."""
    result = generate_detailed(question, evidence, settings, visual_payloads, provider)
    return result.answer, result.provider, result.model_ms, result.usage.total_tokens
