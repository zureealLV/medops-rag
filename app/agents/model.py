"""OpenAI-compatible provider with bounded retry and offline fallback."""

from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from collections import Counter, deque
from contextlib import asynccontextmanager, contextmanager
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
CircuitState = Literal["closed", "open", "half_open"]


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


class ModelProviderCircuitOpenError(RuntimeError):
    """The Provider breaker rejects calls until recovery or a probe succeeds."""

    def __init__(self, *, state: CircuitState, retry_after_seconds: int) -> None:
        super().__init__(f"model provider circuit is {state}")
        self.state = state
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class _CircuitLease:
    epoch: int
    probe: bool = False


def _is_retriable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


class ModelProvider:
    """Process-local sync compatibility client plus fair async provider runtime.

    Production ``/answer`` traffic uses the async path: logical requests retain
    bounded outstanding admission during retry backoff, while actual HTTP
    attempts use a tenant-aware round-robin scheduler.  The synchronous gate is
    retained for batch/benchmark compatibility and is deliberately documented
    as a separate, non-fair path.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.model_max_concurrency < 1:
            raise ValueError("MODEL_MAX_CONCURRENCY must be at least 1")
        if settings.model_max_concurrency_per_tenant < 1:
            raise ValueError("MODEL_MAX_CONCURRENCY_PER_TENANT must be at least 1")
        if settings.model_max_queue_waiters < 0:
            raise ValueError("MODEL_MAX_QUEUE_WAITERS cannot be negative")
        if settings.model_max_queue_waiters_per_tenant < 0:
            raise ValueError("MODEL_MAX_QUEUE_WAITERS_PER_TENANT cannot be negative")
        if settings.model_queue_timeout_seconds < 0:
            raise ValueError("MODEL_QUEUE_TIMEOUT_SECONDS cannot be negative")
        if settings.model_overload_retry_after_seconds < 1:
            raise ValueError("MODEL_OVERLOAD_RETRY_AFTER_SECONDS must be at least 1")
        if settings.model_circuit_failure_threshold < 1:
            raise ValueError("MODEL_CIRCUIT_FAILURE_THRESHOLD must be at least 1")
        if settings.model_circuit_recovery_seconds <= 0:
            raise ValueError("MODEL_CIRCUIT_RECOVERY_SECONDS must be positive")
        if settings.model_shutdown_timeout_seconds <= 0:
            raise ValueError("MODEL_SHUTDOWN_TIMEOUT_SECONDS must be positive")

        self.max_concurrency = settings.model_max_concurrency
        self.max_concurrency_per_tenant = min(
            settings.model_max_concurrency_per_tenant, self.max_concurrency
        )
        self.max_queue_waiters = settings.model_max_queue_waiters
        self.max_queue_waiters_per_tenant = min(
            settings.model_max_queue_waiters_per_tenant, self.max_queue_waiters
        )
        self.queue_timeout_seconds = settings.model_queue_timeout_seconds
        self.retry_after_seconds = settings.model_overload_retry_after_seconds
        self.circuit_failure_threshold = settings.model_circuit_failure_threshold
        self.circuit_recovery_seconds = settings.model_circuit_recovery_seconds
        self.shutdown_timeout_seconds = settings.model_shutdown_timeout_seconds
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
        self._async_transport = async_transport
        self._async_timeout = settings.model_timeout_seconds
        self._async_client: httpx.AsyncClient | None = None
        self._async_condition = asyncio.Condition()
        self._async_waiters: deque[object] = deque()
        self._async_waiter_tenants: dict[object, str] = {}
        self._async_waiter_tenant_order: deque[str] = deque()
        self._async_last_tenant: str | None = None
        self._async_active = 0
        self._async_outstanding = 0
        self._async_active_by_tenant: Counter[str] = Counter()
        self._async_outstanding_by_tenant: Counter[str] = Counter()
        self._state_lock = threading.Lock()
        self._state_changed = threading.Condition(self._state_lock)
        self._closed = False
        self._sync_client_closed = False
        self._active = 0
        self._admitted = 0
        self._circuit_state: CircuitState = "closed"
        self._circuit_failures = 0
        self._circuit_opened_at = 0.0
        self._circuit_epoch = 0
        self._half_open_probe_active = False

    @property
    def is_closed(self) -> bool:
        with self._state_lock:
            return self._closed

    @property
    def is_async_started(self) -> bool:
        return self._async_client is not None

    async def start(self) -> None:
        """Create the event-loop-owned client during the application lifespan."""
        with self._state_lock:
            if self._closed:
                raise RuntimeError("model provider is closed")
            if self._async_client is not None:
                return
            self._async_client = httpx.AsyncClient(
                timeout=self._async_timeout,
                limits=httpx.Limits(
                    max_connections=self.max_concurrency,
                    max_keepalive_connections=self.max_concurrency,
                ),
                transport=self._async_transport,
            )

    @asynccontextmanager
    async def async_admission(self, tenant_id: str):
        """Retain one bounded outstanding-request budget across retries/backoff."""
        client = self._async_client
        if client is None:
            raise RuntimeError("model provider async client has not been started")
        started = time.perf_counter()
        async with self._async_condition:
            if self.is_closed:
                raise RuntimeError("model provider is closed")
            if self._async_outstanding >= self.max_concurrency + self.max_queue_waiters:
                raise self._overload("queue_full", started)
            tenant_limit = self.max_concurrency_per_tenant + self.max_queue_waiters_per_tenant
            if self._async_outstanding_by_tenant[tenant_id] >= tenant_limit:
                raise self._overload("queue_full", started)
            self._async_outstanding += 1
            self._async_outstanding_by_tenant[tenant_id] += 1
        try:
            yield client
        finally:
            async with self._async_condition:
                self._async_outstanding -= 1
                self._async_outstanding_by_tenant[tenant_id] -= 1
                if self._async_outstanding_by_tenant[tenant_id] == 0:
                    del self._async_outstanding_by_tenant[tenant_id]
                self._async_condition.notify_all()

    @asynccontextmanager
    async def async_attempt_slot(self, tenant_id: str):
        """Acquire only a network-attempt slot using one fair, eligible FIFO queue."""
        started = time.perf_counter()
        token = object()
        acquired = False
        async with self._async_condition:
            if self.is_closed:
                raise RuntimeError("model provider is closed")
            if self._can_start_async(tenant_id) and self._first_eligible_waiter() is None:
                self._activate_async(tenant_id)
                acquired = True
            else:
                self._enqueue_async_waiter(token, tenant_id)
                try:
                    async with asyncio.timeout(self.queue_timeout_seconds):
                        while self._first_eligible_waiter() is not token:
                            if self.is_closed:
                                raise RuntimeError("model provider is closed")
                            await self._async_condition.wait()
                        self._remove_async_waiter(token)
                        self._activate_async(tenant_id)
                        acquired = True
                except TimeoutError:
                    if token in self._async_waiters:
                        self._remove_async_waiter(token)
                        self._async_condition.notify_all()
                    raise self._overload("queue_timeout", started) from None
                except BaseException:
                    if token in self._async_waiters:
                        self._remove_async_waiter(token)
                        self._async_condition.notify_all()
                    raise
        try:
            yield
        finally:
            if acquired:
                async with self._async_condition:
                    self._async_active -= 1
                    self._async_active_by_tenant[tenant_id] -= 1
                    if self._async_active_by_tenant[tenant_id] == 0:
                        del self._async_active_by_tenant[tenant_id]
                    self._async_condition.notify_all()

    @asynccontextmanager
    async def async_request_slot(self, tenant_id: str):
        """Compatibility context combining outstanding admission and one attempt."""
        async with self.async_admission(tenant_id) as client:
            async with self.async_attempt_slot(tenant_id):
                yield client

    def _can_start_async(self, tenant_id: str) -> bool:
        return (
            self._async_active < self.max_concurrency
            and self._async_active_by_tenant[tenant_id] < self.max_concurrency_per_tenant
        )

    def _first_eligible_waiter(self) -> object | None:
        if self._async_active >= self.max_concurrency:
            return None
        tenants = list(self._async_waiter_tenant_order)
        if not tenants:
            return None
        start = 0
        if self._async_last_tenant in tenants and len(tenants) > 1:
            start = (tenants.index(self._async_last_tenant) + 1) % len(tenants)
        for offset in range(len(tenants)):
            tenant_id = tenants[(start + offset) % len(tenants)]
            if self._async_active_by_tenant[tenant_id] >= self.max_concurrency_per_tenant:
                continue
            return next(
                token
                for token in self._async_waiters
                if self._async_waiter_tenants[token] == tenant_id
            )
        return None

    def _enqueue_async_waiter(self, token: object, tenant_id: str) -> None:
        self._async_waiters.append(token)
        self._async_waiter_tenants[token] = tenant_id
        if tenant_id not in self._async_waiter_tenant_order:
            self._async_waiter_tenant_order.append(tenant_id)

    def _remove_async_waiter(self, token: object) -> None:
        self._async_waiters.remove(token)
        tenant_id = self._async_waiter_tenants.pop(token)
        if tenant_id not in self._async_waiter_tenants.values():
            self._async_waiter_tenant_order.remove(tenant_id)

    def _activate_async(self, tenant_id: str) -> None:
        self._async_active += 1
        self._async_active_by_tenant[tenant_id] += 1
        self._async_last_tenant = tenant_id

    def capacity_snapshot(self) -> dict[str, int]:
        """Return a best-effort snapshot for synchronous diagnostics/tests."""
        with self._state_lock:
            return {
                "active": self._active + self._async_active,
                "waiting": max(0, self._admitted - self._active) + len(self._async_waiters),
                "active_tenants": len(self._async_active_by_tenant),
                "outstanding": self._admitted + self._async_outstanding,
                "max_concurrency": self.max_concurrency,
                "max_concurrency_per_tenant": self.max_concurrency_per_tenant,
                "max_queue_waiters": self.max_queue_waiters,
                "max_queue_waiters_per_tenant": self.max_queue_waiters_per_tenant,
            }

    async def async_capacity_snapshot(self) -> dict[str, int]:
        """Return a condition-consistent snapshot for async operational APIs."""
        async with self._async_condition:
            with self._state_lock:
                sync_active = self._active
                sync_admitted = self._admitted
            return {
                "active": sync_active + self._async_active,
                "waiting": max(0, sync_admitted - sync_active) + len(self._async_waiters),
                "active_tenants": len(self._async_active_by_tenant),
                "outstanding": sync_admitted + self._async_outstanding,
                "max_concurrency": self.max_concurrency,
                "max_concurrency_per_tenant": self.max_concurrency_per_tenant,
                "max_queue_waiters": self.max_queue_waiters,
                "max_queue_waiters_per_tenant": self.max_queue_waiters_per_tenant,
            }

    def circuit_snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "state": self._circuit_state,
                "consecutive_failures": self._circuit_failures,
                "epoch": self._circuit_epoch,
                "half_open_probe_active": self._half_open_probe_active,
            }

    def _circuit_before_request(self) -> _CircuitLease:
        now = time.monotonic()
        with self._state_lock:
            if self._circuit_state == "open":
                elapsed = now - self._circuit_opened_at
                if elapsed < self.circuit_recovery_seconds:
                    raise ModelProviderCircuitOpenError(
                        state="open",
                        retry_after_seconds=max(
                            1, math.ceil(self.circuit_recovery_seconds - elapsed)
                        ),
                    )
                self._circuit_state = "half_open"
                self._half_open_probe_active = True
                return _CircuitLease(self._circuit_epoch, probe=True)
            if self._circuit_state == "half_open":
                raise ModelProviderCircuitOpenError(
                    state="half_open",
                    retry_after_seconds=max(1, math.ceil(self.circuit_recovery_seconds)),
                )
            return _CircuitLease(self._circuit_epoch)

    def _circuit_success(self, lease: _CircuitLease) -> None:
        with self._state_lock:
            if lease.epoch != self._circuit_epoch:
                return
            if lease.probe and self._circuit_state == "half_open":
                self._circuit_state = "closed"
                self._half_open_probe_active = False
                self._circuit_failures = 0
                self._circuit_epoch += 1
            elif self._circuit_state == "closed":
                self._circuit_failures = 0

    def _circuit_failure(self, lease: _CircuitLease) -> ModelProviderCircuitOpenError | None:
        with self._state_lock:
            if lease.epoch != self._circuit_epoch:
                return None
            if lease.probe and self._circuit_state == "half_open":
                self._circuit_state = "open"
                self._half_open_probe_active = False
                self._circuit_opened_at = time.monotonic()
                self._circuit_epoch += 1
                return ModelProviderCircuitOpenError(
                    state="open",
                    retry_after_seconds=max(1, math.ceil(self.circuit_recovery_seconds)),
                )
            if self._circuit_state != "closed":
                return ModelProviderCircuitOpenError(
                    state=self._circuit_state,
                    retry_after_seconds=max(1, math.ceil(self.circuit_recovery_seconds)),
                )
            self._circuit_failures += 1
            if self._circuit_failures < self.circuit_failure_threshold:
                return None
            self._circuit_state = "open"
            self._circuit_opened_at = time.monotonic()
            self._circuit_epoch += 1
            return ModelProviderCircuitOpenError(
                state="open",
                retry_after_seconds=max(1, math.ceil(self.circuit_recovery_seconds)),
            )

    def _circuit_cancel(self, lease: _CircuitLease) -> None:
        """Fail safe when a half-open probe is cancelled before an outcome exists."""
        with self._state_lock:
            if (
                lease.probe
                and lease.epoch == self._circuit_epoch
                and self._circuit_state == "half_open"
            ):
                self._circuit_state = "open"
                self._half_open_probe_active = False
                self._circuit_opened_at = time.monotonic()
                self._circuit_epoch += 1

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
            if self._sync_client_closed:
                return
            self._closed = True
            self._state_changed.wait_for(
                lambda: self._admitted == 0,
                timeout=self.shutdown_timeout_seconds,
            )
            self._sync_client_closed = True
        self._client.close()

    async def aclose(self) -> None:
        """Close both event-loop and worker-thread clients without blocking the loop."""
        with self._state_lock:
            self._closed = True
        async with self._async_condition:
            self._async_condition.notify_all()
            try:
                async with asyncio.timeout(self.shutdown_timeout_seconds):
                    while self._async_active or self._async_waiters:
                        await self._async_condition.wait()
            except TimeoutError:
                pass
        client = self._async_client
        if client is not None:
            await client.aclose()
        await asyncio.to_thread(self.close)

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
            circuit_lease = runtime._circuit_before_request()
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
                    runtime._circuit_success(circuit_lease)
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
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                    if attempt < settings.model_max_retries and _is_retriable_provider_error(exc):
                        time.sleep(0.1 * (attempt + 1))
                        continue
                    break
            circuit_error = runtime._circuit_failure(circuit_lease)
            if circuit_error is not None:
                raise circuit_error
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


async def generate_detailed_async(
    question: str,
    evidence: list[Evidence],
    settings: Settings,
    visual_payloads: list[tuple[VisualEvidence, bytes]] | None = None,
    *,
    tenant_id: str,
    provider: ModelProvider,
) -> GenerationResult:
    """Generate online without occupying a worker thread during network I/O."""
    started = time.perf_counter()
    visual_payloads = visual_payloads or []
    if not (settings.model_api_key and settings.model_base_url and settings.model_name):
        answer, offline_provider, tokens = _offline_answer(question, evidence, visual_payloads)
        completion_tokens = len(tokenize(answer))
        return GenerationResult(
            answer,
            offline_provider,
            0.0,
            ModelUsage(
                total_tokens=tokens,
                prompt_tokens=max(0, tokens - completion_tokens),
                completion_tokens=completion_tokens,
            ),
        )
    if visual_payloads and not settings.model_vision_enabled:
        answer, offline_provider, tokens = _offline_answer(question, evidence, visual_payloads)
        completion_tokens = len(tokenize(answer))
        return GenerationResult(
            answer,
            offline_provider,
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
    async with provider.async_admission(tenant_id) as client:
        circuit_lease: _CircuitLease | None = None
        circuit_resolved = False
        try:
            for attempt in range(settings.model_max_retries + 1):
                try:
                    async with provider.async_attempt_slot(tenant_id):
                        if circuit_lease is None:
                            circuit_lease = provider._circuit_before_request()
                        response = await client.post(
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
                    provider._circuit_success(circuit_lease)
                    circuit_resolved = True
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
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                    if attempt < settings.model_max_retries and _is_retriable_provider_error(exc):
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    break
            if circuit_lease is None:
                raise RuntimeError("model provider circuit lease was not acquired")
            circuit_error = provider._circuit_failure(circuit_lease)
            circuit_resolved = True
            if circuit_error is not None:
                raise circuit_error
        finally:
            if circuit_lease is not None and not circuit_resolved:
                provider._circuit_cancel(circuit_lease)

    answer, offline_provider, tokens = _offline_answer(question, evidence, visual_payloads)
    fallback_provider = "offline-visual-fallback" if visual_payloads else "offline-fallback"
    if offline_provider == "offline-extractive+visual-locator":
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
