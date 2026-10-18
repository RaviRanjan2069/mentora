"""Use the offline templates while a local model server is unreachable (e.g. the laptop that
runs Ollama for a hosted demo is off). Opt-in: ``llm.local_fallback: offline``.

Only "cannot reach the model" failures fall back: timeouts and connection errors, HTTP 429
and 5xx, and HTTP 404 (a tunnel whose endpoint is offline). Anything else (a malformed
request, a refused token) is raised as before. After a failure the model is not tried again
for ``retry_after_s`` seconds, so learners do not wait for one timeout after another.
While falling back, ``degraded`` is true and the API reports the back-end as ``offline``,
so the UI shows its "Demo mode" notice instead of passing templates off as model replies.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from mentora.llm.types import Completion, LLMBackend, LLMError, LLMRequest, TransientLLMError

log = logging.getLogger("mentora.llm")


def _unreachable(exc: LLMError) -> bool:
    return isinstance(exc, TransientLLMError) or str(exc).startswith("HTTP 404")


class FallbackBackend:
    def __init__(
        self,
        primary: LLMBackend,
        fallback: LLMBackend,
        *,
        retry_after_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.primary, self.fallback = primary, fallback
        self.name, self.model = primary.name, primary.model
        self.retry_after_s = retry_after_s
        self._clock = clock
        self._down_until = 0.0
        self._lock = threading.Lock()

    @property
    def degraded(self) -> bool:
        return self._clock() < self._down_until

    def _mark_down(self, exc: LLMError) -> None:
        with self._lock:
            if not self.degraded:
                log.warning(
                    "local model unreachable (%s); offline replies for %.0fs",
                    exc,
                    self.retry_after_s,
                )
            self._down_until = self._clock() + self.retry_after_s

    def complete(self, request: LLMRequest) -> Completion:
        if not self.degraded:
            try:
                return self.primary.complete(request)
            except LLMError as exc:
                if not _unreachable(exc):
                    raise
                self._mark_down(exc)
        return self.fallback.complete(request)

    def stream(self, request: LLMRequest, on_text: Callable[[str], None]) -> Completion:
        stream = getattr(self.primary, "stream", None)
        if not self.degraded and stream is not None:
            sent = False

            def relay(piece: str) -> None:
                nonlocal sent
                sent = True
                on_text(piece)

            try:
                result: Completion = stream(request, relay)
                return result
            except LLMError as exc:
                if sent or not _unreachable(exc):
                    raise  # half a reply cannot be completed by another back-end
                self._mark_down(exc)
        completion = self.complete(request)
        on_text(completion.text)
        return completion
