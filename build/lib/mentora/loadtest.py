"""Concurrent-learner load test through the HTTP API (dev login, a short session each).
Used by scripts/load_test.py against a running server and by a small pytest smoke test."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

# Any HTTP client with .get(url) and .post(url, json=...) (httpx.Client, TestClient).
Client = Any


@dataclass
class LoadResult:
    learners: int
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    wall_s: float = 0.0

    def summary(self) -> dict[str, float]:
        lat = sorted(self.latencies_ms) or [0.0]

        def p(q: float) -> float:
            return lat[min(len(lat) - 1, int(q * len(lat)))]

        return {
            "learners": float(self.learners),
            "requests": float(self.requests),
            "errors": float(len(self.errors)),
            "p50_ms": round(statistics.median(lat), 1),
            "p95_ms": round(p(0.95), 1),
            "max_ms": round(lat[-1], 1),
            "throughput_rps": round(self.requests / self.wall_s, 1) if self.wall_s else 0.0,
        }


def _learner(
    make_client: Callable[[], Client], i: int, messages: int
) -> tuple[list[float], list[str]]:
    c = make_client()
    lat: list[float] = []
    errors: list[str] = []

    def call(method: str, url: str, body: Any = None) -> Any:
        t0 = time.perf_counter()
        r = c.post(url, json=body) if method == "POST" else c.get(url)
        lat.append(1000 * (time.perf_counter() - t0))
        if r.status_code >= 400:
            errors.append(f"learner {i}: {method} {url} -> {r.status_code}")
            return None
        return r.json() if r.status_code != 204 else None

    call("POST", "/api/dev/login", {"role": "learner", "name": f"Load {i}"})
    start = call("POST", "/api/sessions", {})
    if not start:
        return lat, errors
    sid = start["session_id"]
    items = call("GET", "/api/items") or []
    call(
        "POST",
        f"/api/sessions/{sid}/messages",
        {"text": "My goal is to finish 2 for loop exercises today"},
    )
    for k in range(messages):
        if items:
            item = items[(i + k) % len(items)]
            call("POST", f"/api/sessions/{sid}/items/{item['id']}/present", {})
            call(
                "POST",
                f"/api/sessions/{sid}/items/{item['id']}/answer",
                {"response": "x", "confidence": 0.5, "seconds": 10},
            )
        call("POST", f"/api/sessions/{sid}/messages", {"text": "can I get a hint?"})
    call("POST", f"/api/sessions/{sid}/end", {})
    return lat, errors


def run_load(
    make_client: Callable[[], Client], learners: int, messages: int, workers: int
) -> LoadResult:
    result = LoadResult(learners)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lat, errs in pool.map(lambda i: _learner(make_client, i, messages), range(learners)):
            result.latencies_ms.extend(lat)
            result.errors.extend(errs)
    result.wall_s = time.perf_counter() - t0
    result.requests = len(result.latencies_ms)
    return result
