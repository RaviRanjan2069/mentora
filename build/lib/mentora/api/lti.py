"""LTI 1.3 launch from Moodle (OIDC third-party login + signed id_token).

Flow: Moodle -> /lti/login (iss, login_hint, ...) -> redirect to the platform's auth URL
with a fresh state + nonce -> Moodle POSTs id_token + state to /lti/launch -> we verify the
RS256 signature against the platform JWKS, the issuer, audience, expiry, nonce, deployment,
message type and LTI version, then sign the user in under a pseudonym.

Implemented directly with PyJWT (see docs/decisions.md D31). Roster (NRPS) and grade
passback (AGS) are not implemented yet.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from mentora.api.deps import Role, User, sign_in
from mentora.config.settings import Settings
from mentora.db import models as m
from mentora.privacy import pseudonymize

router = APIRouter(prefix="/lti", tags=["lti"])

LTI = "https://purl.imsglobal.org/spec/lti/claim"
TEACHER_ROLES = ("#Instructor", "#Administrator", "#ContentDeveloper", "#TeachingAssistant")
NONCE_TTL_S = 600

JwksFetcher = Callable[[str], dict[str, Any]]


def fetch_jwks(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


def _settings(request: Request) -> Settings:
    s: Settings = request.app.state.settings
    if not (s.lti_issuer and s.lti_client_id and s.lti_auth_login_url and s.lti_key_set_url):
        raise HTTPException(503, "LTI is not configured (see docs/runbook.md)")
    return s


async def _params(request: Request) -> dict[str, str]:
    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update({k: str(v) for k, v in form.items()})
    return params


@router.api_route("/login", methods=["GET", "POST"])
async def login(request: Request) -> RedirectResponse:
    s = _settings(request)
    p = await _params(request)
    if p.get("iss") != s.lti_issuer:
        raise HTTPException(400, "Unknown platform (iss)")
    if p.get("client_id") and p["client_id"] != s.lti_client_id:
        raise HTTPException(400, "Unknown client_id")
    if not p.get("login_hint"):
        raise HTTPException(400, "Missing login_hint")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["lti"] = {"state": state, "nonce": nonce, "at": time.time()}
    query = {
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": s.lti_client_id,
        "redirect_uri": f"{s.public_base_url.rstrip('/')}/lti/launch",
        "login_hint": p["login_hint"],
        "state": state,
        "nonce": nonce,
    }
    if p.get("lti_message_hint"):
        query["lti_message_hint"] = p["lti_message_hint"]
    return RedirectResponse(f"{s.lti_auth_login_url}?{urlencode(query)}", status_code=302)


def verify_id_token(token: str, s: Settings, jwks: dict[str, Any]) -> dict[str, Any]:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        keys = jwt.PyJWKSet.from_dict(jwks)
        key = next((k for k in keys.keys if k.key_id == kid), None)
        if key is None:
            raise HTTPException(401, "Signing key not found in platform JWKS")
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=s.lti_client_id,
            issuer=s.lti_issuer,
            options={"require": ["exp", "iat", "sub", "nonce"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid id_token: {exc}") from exc
    if claims.get(f"{LTI}/message_type") != "LtiResourceLinkRequest":
        raise HTTPException(400, "Unsupported LTI message type")
    if claims.get(f"{LTI}/version") != "1.3.0":
        raise HTTPException(400, "Unsupported LTI version")
    if s.lti_deployment_ids and claims.get(f"{LTI}/deployment_id") not in s.lti_deployment_ids:
        raise HTTPException(401, "Unknown deployment")
    return claims


@router.post("/launch")
async def launch(request: Request) -> RedirectResponse:
    s = _settings(request)
    form = await request.form()
    token, state = str(form.get("id_token", "")), str(form.get("state", ""))
    pending = request.session.pop("lti", None)
    if not pending or not secrets.compare_digest(pending["state"], state):
        raise HTTPException(401, "State mismatch: start the launch from the course page again")
    if time.time() - float(pending["at"]) > NONCE_TTL_S:
        raise HTTPException(401, "Launch expired")
    fetcher: JwksFetcher = getattr(request.app.state, "jwks_fetcher", None) or fetch_jwks
    claims = verify_id_token(token, s, fetcher(s.lti_key_set_url))
    if not secrets.compare_digest(str(claims["nonce"]), pending["nonce"]):
        raise HTTPException(401, "Nonce mismatch")

    roles = claims.get(f"{LTI}/roles", [])
    role: Role = "teacher" if any(r.endswith(TEACHER_ROLES) for r in roles) else "learner"
    user_id = pseudonymize(f"{claims['iss']}|{claims['sub']}", s.pseudonym_salt.get_secret_value())
    name = str(claims.get("given_name") or claims.get("name") or "there")
    if role == "learner":
        with request.app.state.session_factory.begin() as db:
            if db.get(m.Learner, user_id) is None:
                db.add(m.Learner(id=user_id))
    sign_in(request, User(user_id, role, name, "lti"))
    target = "/app/#/teacher" if role == "teacher" else "/app/#/"
    return RedirectResponse(target, status_code=303)
