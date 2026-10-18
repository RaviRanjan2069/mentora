"""Local model unreachable -> offline templates, honestly reported; other errors still raise."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from mentora.api.deps import effective_llm_backend
from mentora.llm.backends.fallback import FallbackBackend
from mentora.llm.types import Completion, LLMError, LLMRequest, TransientLLMError

REQ = LLMRequest(system="s", messages=(), max_tokens=50, prompt_id="rag/answer")


class Scripted:
    """A back-end that raises the queued errors, then answers."""

    name, model = "local", "llama3.2:3b"

    def __init__(self, errors: list[LLMError], partial: str = "") -> None:
        self.errors, self.partial, self.calls = errors, partial, 0

    def complete(self, request: LLMRequest) -> Completion:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return Completion("model reply", self.model, 1, 2)

    def stream(self, request: LLMRequest, on_text: Callable[[str], None]) -> Completion:
        if self.partial:
            on_text(self.partial)
        return self.complete(request)


class Offline:
    name, model = "offline", "offline-templates"

    def complete(self, request: LLMRequest) -> Completion:
        return Completion("template reply", self.model, 1, 2)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.mark.parametrize(
    "error", [TransientLLMError("ConnectError"), LLMError("HTTP 404: ERR_NGROK_3200 offline")]
)
def test_unreachable_model_falls_back_then_recovers(error: LLMError) -> None:
    clock = Clock()
    primary = Scripted([error])
    backend = FallbackBackend(primary, Offline(), retry_after_s=60, clock=clock)
    assert backend.complete(REQ).text == "template reply"
    assert backend.degraded
    assert backend.complete(REQ).text == "template reply"
    assert primary.calls == 1  # no new attempt (and no new timeout) inside the window
    clock.t = 61
    assert not backend.degraded
    assert backend.complete(REQ).text == "model reply"


def test_other_errors_are_not_hidden() -> None:
    backend = FallbackBackend(
        Scripted([LLMError("HTTP 401: bad token")]), Offline(), retry_after_s=60
    )
    with pytest.raises(LLMError, match="401"):
        backend.complete(REQ)
    assert not backend.degraded


def test_streaming_falls_back_only_before_any_text() -> None:
    got: list[str] = []
    backend = FallbackBackend(Scripted([TransientLLMError("timeout")]), Offline(), retry_after_s=60)
    assert backend.stream(REQ, got.append).text == "template reply"
    assert got == ["template reply"]
    half = FallbackBackend(
        Scripted([TransientLLMError("reset")], partial="Half a"), Offline(), retry_after_s=60
    )
    with pytest.raises(TransientLLMError):
        half.stream(REQ, got.append)


def test_api_reports_offline_while_degraded() -> None:
    clock = Clock()
    backend = FallbackBackend(
        Scripted([TransientLLMError("x")]), Offline(), retry_after_s=60, clock=clock
    )
    state = SimpleNamespace(
        settings=SimpleNamespace(llm=SimpleNamespace(backend="local")),
        orchestrator=SimpleNamespace(client=SimpleNamespace(backend=backend)),
    )
    assert effective_llm_backend(state) == "local"
    backend.complete(REQ)
    assert effective_llm_backend(state) == "offline"
    clock.t = 120
    assert effective_llm_backend(state) == "local"
