"""Token-checking gateway in front of a local Ollama, for a tunnel to a hosted Mentora.

    python scripts/ollama_gateway.py --token <secret>          # listens on 127.0.0.1:11435
    cloudflared tunnel --url http://127.0.0.1:11435             # public https URL

Never tunnel Ollama itself: its API can also pull, create and delete models. This gateway
forwards only what Mentora's local back-end uses (chat completions, the model list and the
warm-up call) and only with ``Authorization: Bearer <token>``. Set the same token as
MENTORA_LOCAL_LLM_API_KEY and MENTORA_LOCAL_LLM_BASE_URL=<tunnel url>/v1 on the server.
"""

from __future__ import annotations

import argparse
import hmac
import os
from collections.abc import AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

ALLOWED = {
    ("POST", "/v1/chat/completions"),
    ("GET", "/v1/models"),
    ("POST", "/api/generate"),
}
MAX_BODY_BYTES = 1_000_000


def make_app(token: str, upstream: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    client = httpx.AsyncClient(base_url=upstream, timeout=httpx.Timeout(600.0, connect=5.0))
    expected = f"Bearer {token}".encode()

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward(path: str, request: Request) -> StreamingResponse:
        given = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(given, expected):
            raise HTTPException(401, "Unauthorized")
        if (request.method, f"/{path}") not in ALLOWED:
            raise HTTPException(404, "Not found")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large")
        upstream_req = client.build_request(
            request.method,
            f"/{path}",
            content=body,
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
        resp = await client.send(upstream_req, stream=True)

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            chunks(),
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token", default=os.environ.get("OLLAMA_GATEWAY_TOKEN", ""))
    ap.add_argument("--upstream", default="http://127.0.0.1:11434")
    ap.add_argument("--port", type=int, default=11435)
    args = ap.parse_args()
    if len(args.token) < 16:
        ap.error("--token (or OLLAMA_GATEWAY_TOKEN) must be at least 16 characters")
    uvicorn.run(make_app(args.token, args.upstream), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
