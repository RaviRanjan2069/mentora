"""Real-time replies: the client streams learner-facing text to a sink, the local back-end
parses OpenAI-style server-sent events, and JSON rubric calls are never streamed."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
from pydantic import BaseModel

from mentora.llm.backends.fake import FakeLLM
from mentora.llm.backends.local import LocalBackend
from mentora.llm.client import LLMClient, streaming
from mentora.llm.prompts import RenderedPrompt
from mentora.llm.types import Completion, LLMRequest


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def begin(self, prompt_id: str) -> None:
        self.events.append(("begin", prompt_id))

    def delta(self, text: str) -> None:
        self.events.append(("delta", text))


class Streamer(FakeLLM):
    """A fake back-end that streams its reply word by word."""

    def stream(self, request: LLMRequest, on_text: Callable[[str], None]) -> Completion:
        done = self.complete(request)
        for i, word in enumerate(done.text.split(" ")):
            on_text(word if i == 0 else f" {word}")
        return done


def _prompt(prompt_id: str) -> RenderedPrompt:
    return RenderedPrompt(prompt_id, 1, "system", "user")


def test_reply_text_is_streamed_to_the_sink_in_pieces() -> None:
    client = LLMClient(Streamer(default=lambda r: "range stops before the end"))
    sink = Sink()
    with streaming(sink):
        text = client.generate(_prompt("tutor/answer"))
    assert text == "range stops before the end"
    assert sink.events[0] == ("begin", "tutor/answer")
    assert "".join(t for kind, t in sink.events if kind == "delta") == text
    assert len(sink.events) == 6  # begin + 5 words


def test_rubric_calls_and_calls_outside_a_turn_are_not_streamed() -> None:
    class Verdict(BaseModel):
        ok: bool

    client = LLMClient(Streamer(default=lambda r: '{"ok": true}'))
    sink = Sink()
    with streaming(sink):
        client.generate(_prompt("learner_model/srl_tagger"))
        assert client.generate(_prompt("agents/turn:X.y.Socratic"), Verdict).ok
    assert sink.events == []
    client.generate(_prompt("tutor/answer"))  # no sink installed: nothing to stream to
    assert sink.events == []


def test_a_backend_without_streaming_hands_over_the_whole_reply() -> None:
    client = LLMClient(FakeLLM(default=lambda r: "whole reply"))
    sink = Sink()
    with streaming(sink):
        client.generate(_prompt("agents/turn:ContentTutor.graded_hint.Socratic"))
    assert sink.events == [
        ("begin", "agents/turn:ContentTutor.graded_hint.Socratic"),
        ("delta", "whole reply"),
    ]


def test_local_backend_parses_server_sent_events() -> None:
    chunks = ["Ranges ", "stop ", "early."]
    events = [{"model": "llama3.2:3b", "choices": [{"delta": {"content": c}}]} for c in chunks]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    backend = LocalBackend(
        "llama3.2:3b", "http://ollama.test/v1", transport=httpx.MockTransport(handler)
    )
    pieces: list[str] = []
    request = LLMRequest(system="s", messages=(), max_tokens=50, prompt_id="tutor/answer")
    done = backend.stream(request, pieces.append)
    assert pieces == chunks and done.text == "Ranges stop early." and done.model == "llama3.2:3b"
    assert seen[0]["stream"] is True
