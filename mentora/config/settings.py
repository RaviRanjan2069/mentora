"""Typed settings loaded from defaults.yaml, overridable by environment variables.

Precedence (highest first): constructor kwargs, environment / .env, defaults.yaml.
Nested keys use a double underscore: ``MENTORA_SAFETY__THETA_PRE=0.6``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULTS_FILE = Path(__file__).with_name("defaults.yaml")

Probability = Field(ge=0.0, le=1.0)


class AppSettings(BaseModel):
    name: str
    mode: Literal["adaptive", "static"]
    concepts_file: Path


class ModelPrice(BaseModel):
    input: float = Field(ge=0)  # USD per 1M tokens
    output: float = Field(ge=0)


class LLMSettings(BaseModel):
    # "auto" is resolved when settings load: hosted if an API key is configured, else offline.
    backend: Literal["auto", "offline", "fake", "hosted", "local"]
    hosted_model: str
    hosted_effort: Literal["low", "medium", "high", "xhigh", "max"]
    hosted_fallbacks: bool
    local_model: str
    local_temperature: float = Field(ge=0)
    max_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    retry_backoff_s: float = Field(ge=0)
    schema_repair_attempts: int = Field(ge=0)
    cache_enabled: bool
    cache_dir: Path
    pricing: dict[str, ModelPrice]


class RagSettings(BaseModel):
    chunk_tokens: int = Field(gt=0)
    beta: float = Probability
    top_k_retrieve: int = Field(gt=0)
    top_k_rerank: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    embedder: Literal["sentence_transformers", "hashing"]
    embedding_model: str
    embedding_dim: int = Field(gt=0)
    reranker: Literal["cross_encoder", "lexical"]
    reranker_model: str
    grounding_judge: Literal["nli", "llm", "lexical"]
    nli_model: str
    lexical_entailment_threshold: float = Probability
    max_regenerations: int = Field(ge=0)
    uncertain_reply: str
    offtopic_overlap: float = Probability
    offtopic_reply: str
    answer_mode: Literal["open", "course_only"] = "open"
    unverified: Literal["label", "escalate"] = "label"
    answer_max_tokens: int = Field(default=500, gt=0)
    history_messages: int = Field(default=6, ge=0)
    answer_passages: int = Field(default=3, gt=0)
    answer_regenerations: int = Field(default=1, ge=0)


class MemorySettings(BaseModel):
    recall_k: int = Field(gt=0)
    curator_gate: float = Probability
    merge_cosine: float = Probability
    prune_delta: int = Field(ge=0)
    q_min: float = Probability
    recency_half_life_days: float = Field(gt=0)
    max_candidates: int = Field(gt=0)
    reflector_mode: Literal["auto", "llm", "heuristic"]
    min_specific_words: int = Field(gt=0)
    curator_weights: tuple[float, float, float, float]


class JobSettings(BaseModel):
    mode: Literal["inline", "celery"]


class SafetySettings(BaseModel):
    theta_pre: float = Probability
    n_max: int = Field(ge=0)
    window_minutes: int = Field(gt=0)
    max_solution_code_lines: int = Field(ge=1)
    integrity_regenerations: int = Field(ge=0)
    escalate_reply: str
    distress_reply: str
    support_resources: list[str] = Field(min_length=1)
    integrity_fallback_reply: str


class AgentSettings(BaseModel):
    max_reply_sentences: int = Field(gt=0)


class DropoutWeights(BaseModel):
    bias: float
    sessions_per_week: float
    time_on_task_hours: float
    idle_ratio: float


class LearnerModelSettings(BaseModel):
    calibration_eta: float = Probability
    calibration_init: float = Probability
    hmm_states_min: int = Field(ge=1)
    hmm_states_max: int = Field(ge=1)
    hmm_iterations: int = Field(gt=0)
    hmm_restarts: int = Field(gt=0)
    indicator_window: int = Field(gt=0)
    tagger_mode: Literal["auto", "llm", "trace_only"]
    mastery_model: Literal["count", "dkt", "akt"]
    model_dir: Path
    count_prior: tuple[float, float]
    kt_hidden: int = Field(gt=0)
    kt_heads: int = Field(gt=0)
    kt_epochs: int = Field(gt=0)
    kt_lr: float = Field(gt=0)
    kt_batch_size: int = Field(gt=0)
    kt_test_fraction: float = Field(gt=0, lt=1)
    kt_seed: int
    sdl_thresholds: tuple[float, float, float]
    idle_minutes: float = Field(gt=0)
    engagement_window_days: int = Field(gt=0)
    dropout_weights: DropoutWeights
    norm_sessions_per_week: float = Field(gt=0)
    norm_time_on_task_hours: float = Field(gt=0)


class PolicySettings(BaseModel):
    mode: Literal["collect", "deploy"]
    collect_temperature: float = Field(gt=0)
    explore_on_requests: bool = True
    confidence_check_every: int = Field(gt=0)
    novelty_beta: float = Field(ge=0)
    n_state_clusters: int = Field(gt=0)
    ensemble_m: int = Field(gt=0)
    kappa: float = Field(ge=0)
    tau_u: float | None
    gamma: float = Probability
    seed: int


class RewardSettings(BaseModel):
    lambda_k: float
    lambda_s: float
    lambda_g: float
    lambda_d: float
    lambda_l: float
    omega: float
    action_cost: float = Field(ge=0)
    escalate_cost: float = Field(ge=0)


class OfflineSettings(BaseModel):
    method: Literal["cql_ensemble", "tabular"]
    hidden: int = Field(gt=0)
    epochs: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    lr: float = Field(gt=0)
    cql_alpha: float = Field(ge=0)
    target_tau: float = Field(gt=0, le=1)
    tau_u_quantile: float = Probability
    tabular_min_visits: int = Field(ge=1)
    val_fraction: float = Field(gt=0, lt=1)
    min_episodes: int = Field(gt=0)
    fqe_iterations: int = Field(gt=0)
    ridge_alpha: float = Field(gt=0)
    weight_clip: float = Field(gt=1)
    min_ess_fraction: float = Probability
    bootstrap: int = Field(gt=0)
    lcb_alpha: float = Field(gt=0, lt=0.5)
    sim_sessions: int = Field(gt=0)
    sim_turns: int = Field(gt=0)
    fairness_min_group_episodes: int = Field(gt=0)


class GoalSettings(BaseModel):
    attain_mastery: float = Probability
    quiz_max_attempts: int = Field(gt=0)


class PrivacySettings(BaseModel):
    retention_days: int = Field(gt=0)


class EscalationSettings(BaseModel):
    target_rate: float = Probability


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MENTORA_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        yaml_file=DEFAULTS_FILE,
    )

    # Deployment-specific values (env only, not in defaults.yaml).
    database_url: str = "sqlite:///./mentora_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    hosted_llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("MENTORA_HOSTED_LLM_API_KEY", "ANTHROPIC_API_KEY"),
    )
    local_llm_base_url: str = "http://localhost:11434/v1"
    # Bearer token for a local model server behind an authenticating gateway (optional).
    local_llm_api_key: SecretStr = SecretStr("")
    pseudonym_salt: SecretStr = SecretStr("dev-only-salt")
    lti_issuer: str = ""
    lti_client_id: str = ""
    lti_deployment_ids: list[str] = Field(default_factory=list)
    lti_auth_login_url: str = ""
    lti_key_set_url: str = ""
    public_base_url: str = "http://localhost:8000"
    session_secret: SecretStr = SecretStr("dev-only-session-secret-change-me")
    # Dev login lets you pick learner/teacher without Moodle. Turn it off in production.
    dev_login: bool = True
    # When set, dev login as a teacher needs this code (public demos without Moodle).
    dev_teacher_code: SecretStr = SecretStr("")
    # LTI launches inside a Moodle iframe need SameSite=None + HTTPS cookies.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_https_only: bool = False

    app: AppSettings
    llm: LLMSettings
    rag: RagSettings
    memory: MemorySettings
    jobs: JobSettings
    safety: SafetySettings
    agents: AgentSettings
    learner_model: LearnerModelSettings
    policy: PolicySettings
    reward: RewardSettings
    goals: GoalSettings
    offline: OfflineSettings
    privacy: PrivacySettings
    escalation: EscalationSettings

    @model_validator(mode="after")
    def _resolve_auto_backend(self) -> Settings:
        if self.llm.backend == "auto":
            backend = "hosted" if self.hosted_llm_api_key.get_secret_value() else "offline"
            self.llm = self.llm.model_copy(update={"backend": backend})
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests call ``get_settings.cache_clear()`` after patching env."""
    return Settings()  # sections come from the YAML source
