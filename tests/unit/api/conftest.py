from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from mentora.api.main import create_app
from mentora.config import Settings, get_settings
from mentora.course import load_course
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.orchestrator.turn import Orchestrator
from mentora.rag import build_pipeline
from tests.unit.orchestrator.conftest import ROOT, Clock, seeded_course, tutor_reply

__all__ = ["seeded_course"]

ISS = "https://moodle.example.edu"
CLIENT_ID = "mentora-client"
DEPLOYMENT = "1"
LTI = "https://purl.imsglobal.org/spec/lti/claim"


class Platform:
    """A simulated Moodle: signs LTI 1.3 id_tokens with its own RSA key."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "platform-key-1"
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwks = {"keys": [{**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}]}

    def id_token(self, nonce: str, *, sub: str, roles: list[str], **override: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISS,
            "aud": CLIENT_ID,
            "sub": sub,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "given_name": "Asha",
            f"{LTI}/message_type": "LtiResourceLinkRequest",
            f"{LTI}/version": "1.3.0",
            f"{LTI}/deployment_id": DEPLOYMENT,
            f"{LTI}/roles": roles,
            f"{LTI}/context": {"id": "course-42", "title": "Intro to Programming"},
            f"{LTI}/resource_link": {"id": str(uuid.uuid4())},
        }
        key = override.pop("_key", None) or self.key
        claims.update(override)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": self.kid})


LEARNER_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
TEACHER_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"


def lti_settings() -> Settings:
    return get_settings().model_copy(
        update={
            "lti_issuer": ISS,
            "lti_client_id": CLIENT_ID,
            "lti_deployment_ids": [DEPLOYMENT],
            "lti_auth_login_url": f"{ISS}/mod/lti/auth.php",
            "lti_key_set_url": f"{ISS}/mod/lti/certs.php",
            "policy": get_settings().policy.model_copy(update={"mode": "deploy"}),
        }
    )


@pytest.fixture
def platform() -> Platform:
    return Platform()


@pytest.fixture
def app(session_factory: sessionmaker[Session], seeded_course: int, platform: Platform) -> FastAPI:
    settings = lti_settings()
    application = create_app(settings, session_factory)
    application.state.orchestrator = Orchestrator(
        settings,
        session_factory,
        client=LLMClient(FakeLLM(default=tutor_reply)),
        course=load_course(ROOT / "data" / "concepts.yaml"),
        rag=build_pipeline(settings, session_factory, seeded_course),
        clock=Clock(datetime(2026, 9, 9, 10, tzinfo=UTC)),
    )
    application.state.jwks_fetcher = lambda url: platform.jwks
    return application


def client_for(app: FastAPI) -> TestClient:
    return TestClient(app)


def dev_login(app: FastAPI, role: str, name: str = "Asha") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/dev/login", json={"role": role, "name": name})
    assert r.status_code == 200, r.text
    return c


def lti_launch(
    app: FastAPI, platform: Platform, *, sub: str, roles: list[str], **override: Any
) -> tuple[TestClient, Any]:
    c = TestClient(app)
    r = c.get(
        "/lti/login",
        params={
            "iss": ISS,
            "login_hint": sub,
            "client_id": CLIENT_ID,
            "target_link_uri": "http://testserver/lti/launch",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["http://localhost:8000/lti/launch"]
    nonce = override.pop("nonce", q["nonce"][0])
    state = override.pop("state", q["state"][0])
    token = platform.id_token(nonce, sub=sub, roles=roles, **override)
    resp = c.post("/lti/launch", data={"id_token": token, "state": state}, follow_redirects=False)
    return c, resp
