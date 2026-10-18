"""Hosted back-end: Claude via the official Anthropic SDK.

Retries are done once, in ``LLMClient``, so the SDK's own retries are switched off.
Refusal fallbacks are on by default: on a policy decline the API re-runs the request on
the model Anthropic recommends for that refusal category, inside the same call.
"""

from __future__ import annotations

from typing import Any

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from mentora.llm.types import (
    Completion,
    LLMError,
    LLMRefusalError,
    LLMRequest,
    TransientLLMError,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

_TRANSIENT = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
)


class HostedBackend:
    name = "hosted"

    def __init__(
        self,
        model: str,
        *,
        effort: str = "medium",
        fallbacks: bool = True,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        http_client: Any = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        # With no key the SDK resolves its own credentials (ANTHROPIC_API_KEY, profiles).
        kwargs: dict[str, Any] = {"timeout": timeout_s, "max_retries": 0}
        if api_key:
            kwargs["api_key"] = api_key
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = anthropic.Anthropic(**kwargs)

    def complete(self, request: LLMRequest) -> Completion:
        output_config: BetaOutputConfigParam = {"effort": self.effort}  # type: ignore[typeddict-item]
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        messages: list[BetaMessageParam] = [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        try:
            if self.fallbacks:
                response = self._client.beta.messages.create(
                    model=self.model,
                    max_tokens=request.max_tokens,
                    system=request.system,
                    messages=messages,
                    output_config=output_config,
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                )
            else:
                response = self._client.beta.messages.create(
                    model=self.model,
                    max_tokens=request.max_tokens,
                    system=request.system,
                    messages=messages,
                    output_config=output_config,
                )
        except _TRANSIENT as exc:
            raise TransientLLMError(f"{type(exc).__name__}: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientLLMError(f"HTTP {exc.status_code}: {exc.message}") from exc
            raise LLMError(f"HTTP {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise LLMRefusalError(f"model declined (category={category})")
        text = "".join(b.text for b in response.content if b.type == "text")
        return Completion(
            text=text,
            model=response.model,  # may be the fallback model
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=str(response.stop_reason),
            extra={"request_id": getattr(response, "_request_id", None)},
        )
