from __future__ import annotations

import pytest

from mentora.config import Settings, get_settings
from mentora.db.models import EMBEDDING_DIM


def test_section7_defaults_load_from_yaml() -> None:
    s = get_settings()
    assert s.app.name == "Mentora"
    assert s.app.mode == "adaptive"
    assert s.rag.chunk_tokens == 300
    assert s.rag.beta == 0.4
    assert (s.rag.top_k_retrieve, s.rag.top_k_rerank) == (20, 4)
    assert s.memory.recall_k == 5
    assert s.memory.curator_gate == 0.6
    assert s.memory.merge_cosine == 0.9
    assert s.safety.theta_pre == 0.5
    assert (s.safety.n_max, s.safety.window_minutes) == (3, 15)
    assert s.learner_model.calibration_eta == 0.2
    assert s.policy.ensemble_m == 5
    assert s.policy.kappa == 1.0
    assert s.policy.gamma == 0.95
    assert s.privacy.retention_days == 365
    assert s.escalation.target_rate == 0.05


def test_env_overrides_nested_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MENTORA_SAFETY__THETA_PRE", "0.65")
    monkeypatch.setenv("MENTORA_APP__MODE", "static")
    get_settings.cache_clear()
    s = get_settings()
    assert s.safety.theta_pre == 0.65
    assert s.app.mode == "static"
    assert s.safety.n_max == 3  # untouched siblings keep YAML defaults


def test_invalid_override_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MENTORA_SAFETY__THETA_PRE", "1.5")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


def test_embedding_dim_matches_schema() -> None:
    assert get_settings().rag.embedding_dim == EMBEDDING_DIM


def test_secrets_are_not_printed() -> None:
    assert "dev-only-salt" not in repr(get_settings())


def test_auto_backend_uses_claude_only_when_a_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "MENTORA_HOSTED_LLM_API_KEY", "MENTORA_LLM__BACKEND"):
        monkeypatch.delenv(name, raising=False)

    def load() -> Settings:
        return Settings(_env_file=None)  # type: ignore[call-arg]  # ignore a developer's .env

    assert load().llm.backend == "offline"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    s = load()
    assert s.llm.backend == "hosted"
    assert s.hosted_llm_api_key.get_secret_value() == "sk-ant-test"
    monkeypatch.setenv("MENTORA_LLM__BACKEND", "offline")  # an explicit choice wins
    assert load().llm.backend == "offline"
