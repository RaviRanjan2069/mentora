"""Contract tests: every back-end behaves the same through LLMClient. All offline:
the hosted back-end runs the real Anthropic SDK against an httpx2 mock transport, the
local back-end runs against an httpx mock transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel

from mentora.llm.backends.fake import FakeLLM
from mentora.llm.backends.hosted import FALLBACK_BETA, HostedBackend
from mentora.llm.backends.local import LocalBackend
from mentora.llm.client import LLMClient
from mentora.llm.prompts import RenderedPrompt
from mentora.llm.types import (
    LLMBackend,
    LLMError,
    LLMRefusalError,
    LLMRequest,
    Message,
    TransientLLMError,
)

PROMPT = RenderedPrompt(id="test/echo", version=3, system="Be brief.", user="Say hello.")


class Verdict(BaseModel):
    supported: bool
    reason: str


# Each script entry is (status, reply text); the last entry repeats.
Script = list[tuple[int, str]]


def _hosted(script: Script, seen: list[dict[str, Any]], stop: str = "end_turn") -> LLMBackend:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append({"headers": dict(request.headers), "body": json.loads(request.content)})
        status, text = script[min(len(seen) - 1, len(script) - 1)]
        if status != 200:
            err = {"type": "error", "error": {"type": "api_error", "message": text}}
            return httpx2.Response(status, json=err)
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": text},
                ],
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return HostedBackend("claude-opus-5-5", effort="medium", api_key="test-key", http_client=client)


def _local(script: Script, seen: list[dict[str, Any]]) -> LLMBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"headers": dict(request.headers), "body": json.loads(request.content)})
        status, text = script[min(len(seen) - 1, len(script) - 1)]
        if status != 200:
            return httpx.Response(status, text=text)
        return httpx.Response(
            200,
            json={
                "model": "llama3.1:8b",
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    return LocalBackend(
        "llama3.1:8b", "http://ollama.test/v1", transport=httpx.MockTransport(handler)
    )


def _fake(script: Script, seen: list[dict[str, Any]]) -> LLMBackend:
    failures = sum(1 for s, _ in script if s != 200)
    texts = [t for s, t in script if s == 200]
    return FakeLLM({"test/echo": texts}, fail_first=failures)


BACKENDS: dict[str, Callable[[Script, list[dict[str, Any]]], LLMBackend]] = {
    "hosted": _hosted,
    "local": _local,
    "fake": _fake,
}


def _client(backend: LLMBackend) -> LLMClient:
    return LLMClient(backend, max_retries=2, retry_backoff_s=0.0, sleep=lambda _s: None)


@pytest.mark.parametrize("name", BACKENDS)
def test_plain_text(name: str) -> None:
    client = _client(BACKENDS[name]([(200, "Hello there.")], []))
    assert client.generate(PROMPT) == "Hello there."
    call = client.usage.calls[-1]
    assert (call.prompt_id, call.prompt_version, call.backend) == ("test/echo", 3, name)
    assert call.input_tokens > 0 and call.output_tokens > 0


@pytest.mark.parametrize("name", BACKENDS)
def test_schema_output_is_validated(name: str) -> None:
    reply = '{"supported": true, "reason": "stated in passage"}'
    client = _client(BACKENDS[name]([(200, reply)], []))
    assert client.generate(PROMPT, Verdict) == Verdict(supported=True, reason="stated in passage")


@pytest.mark.parametrize("name", BACKENDS)
def test_transient_errors_are_retried(name: str) -> None:
    seen: list[dict[str, Any]] = []
    client = _client(BACKENDS[name]([(503, "busy"), (429, "slow down"), (200, "ok")], seen))
    assert client.generate(PROMPT) == "ok"
    assert client.usage.calls[-1].attempts == 3


@pytest.mark.parametrize("name", BACKENDS)
def test_retries_give_up(name: str) -> None:
    client = _client(BACKENDS[name]([(503, "busy")] * 5 + [(200, "never")], []))
    with pytest.raises(TransientLLMError):
        client.generate(PROMPT)


@pytest.mark.parametrize("name", ["hosted", "local"])
def test_client_errors_are_not_retried(name: str) -> None:
    seen: list[dict[str, Any]] = []
    client = _client(BACKENDS[name]([(400, "bad request")], seen))
    with pytest.raises(LLMError) as info:
        client.generate(PROMPT)
    assert not isinstance(info.value, TransientLLMError)
    assert len(seen) == 1


def test_hosted_request_shape() -> None:
    seen: list[dict[str, Any]] = []
    backend = _hosted([(200, '{"supported": false, "reason": "no"}')], seen)
    _client(backend).generate(PROMPT, Verdict, history=[Message("user", "earlier")])
    req = seen[0]
    body = req["body"]
    assert FALLBACK_BETA in req["headers"]["anthropic-beta"]
    assert body["fallbacks"] == "default"
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "Be brief."
    assert [m["content"] for m in body["messages"]] == ["earlier", "Say hello."]
    assert body["output_config"]["effort"] == "medium"
    schema = body["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"supported", "reason"}
    assert "thinking" not in body  # adaptive thinking is the model default


def test_hosted_refusal_raises() -> None:
    backend = _hosted([(200, "")], [], stop="refusal")
    with pytest.raises(LLMRefusalError):
        _client(backend).generate(PROMPT)


def test_local_request_uses_json_schema_response_format() -> None:
    seen: list[dict[str, Any]] = []
    _client(_local([(200, '{"supported": true, "reason": "r"}')], seen)).generate(PROMPT, Verdict)
    body = seen[0]["body"]
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["response_format"]["type"] == "json_schema"


def test_fake_minimal_instance_satisfies_schema() -> None:
    assert _client(FakeLLM()).generate(PROMPT, Verdict) == Verdict(supported=False, reason="")


def test_fake_records_requests() -> None:
    fake = FakeLLM()
    _client(fake).generate(PROMPT)
    req: LLMRequest = fake.requests[0]
    assert (req.prompt_id, req.system) == ("test/echo", "Be brief.")
