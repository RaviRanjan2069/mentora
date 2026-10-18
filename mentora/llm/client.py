"""Provider-agnostic LLM client.

``generate(prompt, schema=None)`` returns text, or a validated Pydantic model when a
schema is given. It adds retries with exponential backoff, a one-shot schema repair,
an optional on-disk response cache, and a log record per call with prompt version,
model, tokens, cost and latency.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypeVar, overload

from anthropic import transform_schema
from pydantic import BaseModel, ValidationError

from mentora.config import Settings, get_settings
from mentora.config.settings import ModelPrice
from mentora.llm.prompts import RenderedPrompt
from mentora.llm.types import (
    Completion,
    LLMBackend,
    LLMOutputError,
    LLMRequest,
    Message,
    StreamSink,
    TransientLLMError,
)

log = logging.getLogger("mentora.llm")
T = TypeVar("T", bound=BaseModel)
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# Learner-facing replies (not JSON rubric calls) are streamed to the sink set for the
# current turn, so the UI shows the reply while it is being written.
STREAMED_PROMPTS = ("agents/turn", "tutor/answer", "rag/answer")
_SINK: ContextVar[StreamSink | None] = ContextVar("mentora_stream_sink", default=None)


@contextmanager
def streaming(sink: StreamSink) -> Iterator[None]:
    """Send reply text to ``sink`` while it is generated, for calls made in this context."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


@dataclass(frozen=True)
class CallRecord:
    prompt_id: str
    prompt_version: int
    backend: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int
    attempts: int
    cached: bool


@dataclass
class UsageMeter:
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd or 0.0 for c in self.calls)


class ResponseCache:
    """Content-addressed on-disk cache of completions (for tests and replays)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(backend: str, model: str, request: LLMRequest) -> str:
        payload = {
            "backend": backend,
            "model": model,
            "system": request.system,
            "messages": [asdict(m) for m in request.messages],
            "schema": request.json_schema,
            "max_tokens": request.max_tokens,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> Completion | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        return Completion(**json.loads(path.read_text(encoding="utf-8")))

    def put(self, key: str, completion: Completion) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(
            json.dumps(asdict(completion), ensure_ascii=False), encoding="utf-8"
        )


class LLMClient:
    def __init__(
        self,
        backend: LLMBackend,
        *,
        max_tokens: int = 16000,
        max_retries: int = 2,
        retry_backoff_s: float = 1.0,
        schema_repair_attempts: int = 1,
        pricing: dict[str, ModelPrice] | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.backend = backend
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.schema_repair_attempts = schema_repair_attempts
        self.pricing = pricing or {}
        self.cache = cache
        self.usage = UsageMeter()
        self._sleep = sleep

    @overload
    def generate(
        self,
        prompt: RenderedPrompt,
        schema: None = None,
        *,
        history: Sequence[Message] = (),
        max_tokens: int | None = None,
    ) -> str: ...

    @overload
    def generate(
        self,
        prompt: RenderedPrompt,
        schema: type[T],
        *,
        history: Sequence[Message] = (),
        max_tokens: int | None = None,
    ) -> T: ...

    def generate(
        self,
        prompt: RenderedPrompt,
        schema: type[T] | None = None,
        *,
        history: Sequence[Message] = (),
        max_tokens: int | None = None,
    ) -> str | T:
        messages = (*history, Message("user", prompt.user))
        request = LLMRequest(
            system=prompt.system,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            json_schema=transform_schema(schema) if schema is not None else None,
        )
        completion = self._call(request)
        if schema is None:
            return completion.text

        for attempt in range(self.schema_repair_attempts + 1):
            try:
                return schema.model_validate_json(_strip_fences(completion.text))
            except ValidationError as exc:
                if attempt == self.schema_repair_attempts:
                    raise LLMOutputError(f"{prompt.tag}: invalid output: {exc}") from exc
                request = LLMRequest(
                    system=request.system,
                    messages=(
                        *request.messages,
                        Message("assistant", completion.text),
                        Message(
                            "user",
                            "That output did not match the required JSON schema: "
                            f"{exc.errors(include_url=False)}. Reply with only the corrected "
                            "JSON object.",
                        ),
                    ),
                    max_tokens=request.max_tokens,
                    prompt_id=request.prompt_id,
                    prompt_version=request.prompt_version,
                    json_schema=request.json_schema,
                )
                completion = self._call(request)
        raise AssertionError("unreachable")

    def _call(self, request: LLMRequest) -> Completion:
        start = time.perf_counter()
        sink = _SINK.get()
        if request.json_schema is not None or not request.prompt_id.startswith(STREAMED_PROMPTS):
            sink = None
        key = None
        if self.cache is not None:
            key = ResponseCache.key(self.backend.name, self.backend.model, request)
            hit = self.cache.get(key)
            if hit is not None:
                if sink is not None:
                    sink.begin(request.prompt_id)
                    sink.delta(hit.text)
                self._record(request, hit, start, attempts=0, cached=True)
                return hit

        attempt = 0
        while True:
            attempt += 1
            try:
                completion = self._complete(request, sink)
                break
            except TransientLLMError as exc:
                if attempt > self.max_retries:
                    raise
                delay = self.retry_backoff_s * 2 ** (attempt - 1)
                log.warning(
                    "llm transient error (attempt %d): %s; retry in %.1fs", attempt, exc, delay
                )
                self._sleep(delay)

        if self.cache is not None and key is not None:
            self.cache.put(key, completion)
        self._record(request, completion, start, attempts=attempt, cached=False)
        return completion

    def _complete(self, request: LLMRequest, sink: StreamSink | None) -> Completion:
        if sink is None:
            return self.backend.complete(request)
        sink.begin(request.prompt_id)
        stream = getattr(self.backend, "stream", None)
        if stream is None:  # back-end cannot stream: hand over the whole reply at once
            completion = self.backend.complete(request)
            sink.delta(completion.text)
            return completion
        result: Completion = stream(request, sink.delta)
        return result

    def _record(
        self, request: LLMRequest, c: Completion, start: float, *, attempts: int, cached: bool
    ) -> None:
        price = self.pricing.get(c.model)
        cost = None
        if cached:
            cost = 0.0
        elif price is not None:
            cost = (c.input_tokens * price.input + c.output_tokens * price.output) / 1_000_000
        elif self.backend.name in ("fake", "local"):
            cost = 0.0
        record = CallRecord(
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            backend=self.backend.name,
            model=c.model,
            input_tokens=c.input_tokens,
            output_tokens=c.output_tokens,
            cost_usd=cost,
            latency_ms=int((time.perf_counter() - start) * 1000),
            attempts=attempts,
            cached=cached,
        )
        self.usage.calls.append(record)
        log.info("llm call", extra={"llm": asdict(record)})


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def make_backend(settings: Settings) -> LLMBackend:
    cfg = settings.llm
    if cfg.backend == "hosted":
        from mentora.llm.backends.hosted import HostedBackend

        return HostedBackend(
            cfg.hosted_model,
            effort=cfg.hosted_effort,
            fallbacks=cfg.hosted_fallbacks,
            api_key=settings.hosted_llm_api_key.get_secret_value() or None,
            timeout_s=cfg.timeout_s,
        )
    if cfg.backend == "local":
        from mentora.llm.backends.local import LocalBackend

        return LocalBackend(
            cfg.local_model,
            settings.local_llm_base_url,
            temperature=cfg.local_temperature,
            timeout_s=cfg.timeout_s,
        )
    if cfg.backend == "offline":
        from mentora.llm.backends.offline import OfflineLLM

        return OfflineLLM()
    from mentora.llm.backends.fake import FakeLLM

    return FakeLLM()


def make_client(settings: Settings | None = None, backend: LLMBackend | None = None) -> LLMClient:
    settings = settings or get_settings()
    cfg = settings.llm
    return LLMClient(
        backend or make_backend(settings),
        max_tokens=cfg.max_tokens,
        max_retries=cfg.max_retries,
        retry_backoff_s=cfg.retry_backoff_s,
        schema_repair_attempts=cfg.schema_repair_attempts,
        pricing=cfg.pricing,
        cache=ResponseCache(cfg.cache_dir) if cfg.cache_enabled else None,
    )
