"""Types shared by the LLM client and its back-ends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[Message, ...]
    max_tokens: int
    prompt_id: str = "adhoc"
    prompt_version: int = 0
    json_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = "end_turn"
    extra: dict[str, Any] = field(default_factory=dict)


class LLMBackend(Protocol):
    name: str
    model: str

    def complete(self, request: LLMRequest) -> Completion: ...


class StreamingBackend(LLMBackend, Protocol):
    """A back-end that can also hand out the reply text as it is generated."""

    def stream(self, request: LLMRequest, on_text: Callable[[str], None]) -> Completion: ...


class StreamSink(Protocol):
    """Receives learner-facing reply text while it is generated (see llm.client.streaming).
    ``begin`` starts a new attempt: anything sent before it is discarded."""

    def begin(self, prompt_id: str) -> None: ...

    def delta(self, text: str) -> None: ...


class LLMError(Exception):
    """Non-retryable failure (bad request, auth, invalid model)."""


class TransientLLMError(LLMError):
    """Retryable failure (rate limit, overload, timeout, network)."""


class LLMRefusalError(LLMError):
    """The model declined the request (after any server-side fallback)."""


class LLMOutputError(LLMError):
    """Output did not match the requested schema after repair attempts."""
