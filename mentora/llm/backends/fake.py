"""Deterministic FakeLLM used by every test (no network, no keys).

Responses can be scripted per prompt id (a string, a list consumed in order, or a
function of the request). Unscripted requests get a deterministic echo, or the
minimal JSON instance of the requested schema.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from mentora.llm.types import Completion, LLMRequest, TransientLLMError

Script = str | list[str] | Callable[[LLMRequest], str]


class FakeLLM:
    name = "fake"

    def __init__(
        self,
        script: Mapping[str, Script] | None = None,
        *,
        model: str = "fake-llm",
        fail_first: int = 0,
        default: Callable[[LLMRequest], str] | None = None,
    ) -> None:
        self.model = model
        self._script: dict[str, Script] = dict(script or {})
        self._default = default
        self._fail_remaining = fail_first
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> Completion:
        self.requests.append(request)
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise TransientLLMError("fake transient failure")
        text = self._respond(request)
        prompt_text = request.system + " ".join(m.content for m in request.messages)
        return Completion(
            text=text,
            model=self.model,
            input_tokens=len(prompt_text.split()),
            output_tokens=len(text.split()),
        )

    def _respond(self, request: LLMRequest) -> str:
        entry = self._script.get(request.prompt_id)
        if callable(entry):
            return entry(request)
        if isinstance(entry, list):
            if not entry:
                raise AssertionError(f"FakeLLM script for {request.prompt_id} exhausted")
            return entry.pop(0)
        if isinstance(entry, str):
            return entry
        if self._default is not None:
            return self._default(request)
        if request.json_schema is not None:
            return json.dumps(minimal_instance(request.json_schema, request.json_schema))
        last = request.messages[-1].content if request.messages else ""
        return f"[fake:{request.prompt_id}] {' '.join(last.split()[:12])}"


def minimal_instance(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Any:
    """Smallest value that satisfies a (Pydantic-generated) JSON schema."""
    if "$ref" in schema:
        name = str(schema["$ref"]).split("/")[-1]
        return minimal_instance(root.get("$defs", {})[name], root)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"] or schema[key]
            return minimal_instance(options[0], root)
    kind = schema.get("type", "object")
    if kind == "object":
        props = schema.get("properties", {})
        return {k: minimal_instance(props[k], root) for k in schema.get("required", [])}
    if kind == "array":
        return [minimal_instance(schema.get("items", {}), root)] * int(schema.get("minItems", 0))
    if kind == "string":
        return "x" * int(schema.get("minLength", 0))
    if kind in ("integer", "number"):
        low = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        return int(low) if kind == "integer" else float(low)
    if kind == "boolean":
        return False
    return None
