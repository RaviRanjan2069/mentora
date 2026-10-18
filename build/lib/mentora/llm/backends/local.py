"""Local back-end: an open-weight 7-8B model behind an OpenAI-compatible endpoint
(Ollama ``/v1``, vLLM). Talks plain HTTP, so it has no SDK dependency."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from mentora.llm.types import Completion, LLMError, LLMRequest, TransientLLMError


class LocalBackend:
    name = "local"

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        temperature: float = 0.2,
        timeout_s: float = 60.0,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=headers, transport=transport
        )

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": self.temperature,
        }
        if request.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": request.json_schema, "strict": True},
            }
        return body

    def stream(self, request: LLMRequest, on_text: Callable[[str], None]) -> Completion:
        """Server-sent-events streaming (OpenAI-compatible ``stream: true``)."""
        body = {**self._body(request), "stream": True}
        parts: list[str] = []
        model, finish = self.model, "stop"
        try:
            with self._http.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    error = (
                        TransientLLMError
                        if resp.status_code == 429 or resp.status_code >= 500
                        else LLMError
                    )
                    raise error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    model = str(chunk.get("model", model))
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content") or ""
                        if piece:
                            parts.append(piece)
                            on_text(piece)
                        finish = choice.get("finish_reason") or finish
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientLLMError(f"{type(exc).__name__}: {exc}") from exc
        text = "".join(parts)
        return Completion(text, model, 0, len(text.split()), stop_reason=str(finish))

    def complete(self, request: LLMRequest) -> Completion:
        body = self._body(request)
        try:
            resp = self._http.post("/chat/completions", json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientLLMError(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientLLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=str(data.get("model", self.model)),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", len(text.split()))),
            stop_reason=str(choice.get("finish_reason", "stop")),
        )
