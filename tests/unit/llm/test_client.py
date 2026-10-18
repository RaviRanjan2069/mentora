from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import BaseModel

from mentora.config import get_settings
from mentora.config.settings import ModelPrice
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient, ResponseCache, make_client
from mentora.llm.prompts import RenderedPrompt
from mentora.llm.types import Completion, LLMOutputError, LLMRequest

PROMPT = RenderedPrompt(id="test/p", version=1, system="s", user="u")


class Answer(BaseModel):
    value: int


def test_schema_repair_succeeds_on_second_try() -> None:
    fake = FakeLLM({"test/p": ["not json", '{"value": 4}']})
    client = LLMClient(fake, schema_repair_attempts=1)
    assert client.generate(PROMPT, Answer) == Answer(value=4)
    repair = fake.requests[1].messages
    assert repair[-2].role == "assistant" and repair[-2].content == "not json"
    assert "did not match" in repair[-1].content


def test_schema_failure_after_repairs_raises() -> None:
    client = LLMClient(FakeLLM({"test/p": ["nope", "still nope"]}), schema_repair_attempts=1)
    with pytest.raises(LLMOutputError):
        client.generate(PROMPT, Answer)


def test_code_fences_are_stripped() -> None:
    client = LLMClient(FakeLLM({"test/p": '```json\n{"value": 2}\n```'}))
    assert client.generate(PROMPT, Answer).value == 2


def test_disk_cache_avoids_second_backend_call(tmp_path: Path) -> None:
    fake = FakeLLM({"test/p": ["first", "second"]})
    client = LLMClient(fake, cache=ResponseCache(tmp_path))
    assert client.generate(PROMPT) == "first"
    assert client.generate(PROMPT) == "first"
    assert len(fake.requests) == 1
    assert [c.cached for c in client.usage.calls] == [False, True]
    assert client.usage.calls[1].cost_usd == 0.0


class _PricedBackend:
    name = "hosted"
    model = "claude-opus-5-5"

    def complete(self, request: LLMRequest) -> Completion:
        return Completion("ok", "claude-opus-5-5", input_tokens=1_000_000, output_tokens=500_000)


def test_cost_uses_model_pricing() -> None:
    client = LLMClient(
        _PricedBackend(), pricing={"claude-opus-5-5": ModelPrice(input=4.0, output=20.0)}
    )
    client.generate(PROMPT)
    assert client.usage.cost_usd == pytest.approx(4.0 + 10.0)


def test_each_call_is_logged_with_prompt_version_and_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="mentora.llm"):
        LLMClient(FakeLLM()).generate(PROMPT)
    record = next(r for r in caplog.records if r.name == "mentora.llm")
    data = record.__dict__["llm"]
    assert (data["prompt_id"], data["prompt_version"], data["model"]) == ("test/p", 1, "fake-llm")


def test_make_client_uses_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENTORA_LLM__CACHE_ENABLED", "true")
    monkeypatch.setenv("MENTORA_LLM__CACHE_DIR", str(tmp_path))
    get_settings.cache_clear()
    client = make_client()
    assert client.backend.name == "fake"
    assert client.cache is not None and client.cache.directory == tmp_path
    assert client.max_tokens == get_settings().llm.max_tokens


def test_local_backend_sends_gateway_token() -> None:
    from pydantic import SecretStr

    from mentora.llm.backends.local import LocalBackend
    from mentora.llm.client import make_backend

    s = get_settings()
    s = s.model_copy(
        update={
            "llm": s.llm.model_copy(update={"backend": "local"}),
            "local_llm_api_key": SecretStr("gw-token"),
        }
    )
    backend = make_backend(s)
    assert isinstance(backend, LocalBackend)
    assert backend._http.headers["Authorization"] == "Bearer gw-token"
    s = s.model_copy(update={"local_llm_api_key": SecretStr("")})
    assert "Authorization" not in make_backend(s)._http.headers  # type: ignore[attr-defined]
