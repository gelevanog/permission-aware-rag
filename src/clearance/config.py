"""Runtime settings from environment variables (and an optional .env file). See .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LLMProviderKind = Literal["extractive", "ollama", "openai_compatible", "openrouter", "openai", "anthropic"]
EmbeddingProviderKind = Literal["fastembed", "hash"]
NoAnswerPolicy = Literal["generic", "contact"]

# The local model chosen by measurement (README > Local models): good enough answers at an acceptable CPU latency.
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"
# Free OpenRouter models that answered in the smoke test before the real run (results/smoke.json).
DEFAULT_FREE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_FREE_FALLBACKS = ["dots-studio/dots-3-note-preview:free", "google/gemma-4-31b-it:free"]
DEFAULT_MODELS: dict[str, str] = {
    "extractive": "extractive",
    "ollama": DEFAULT_LOCAL_MODEL,
    "openai_compatible": DEFAULT_LOCAL_MODEL,
    "openrouter": DEFAULT_FREE_MODEL,
    "openai": "gpt-5-mini",
    "anthropic": "claude-sonnet-5",
}
CLOUD_PROVIDERS = frozenset({"openrouter", "openai", "anthropic"})

DEFAULT_NO_ANSWER = "I couldn't find that in documents available to you."
DEFAULT_CONTACT = (
    "If you think you should have access to more documents on this topic, ask your manager or the IT help desk."
)


def _split(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARANCE_", extra="ignore")

    # ---- database
    database_url: str = "postgresql+psycopg://clearance:clearance@localhost:5432/clearance"
    reader_role: str = "clearance_reader"
    """Non-owner role every search runs as (SET LOCAL ROLE), so PostgreSQL row-level security applies."""
    auto_migrate: bool = True
    seed_demo: bool = True
    """On API startup, ingest the demo company corpus when the database has no documents."""
    corpus_dir: Path = Path("data/company")
    directory_file: Path = Path("data/directory.yaml")

    # ---- embeddings
    embedding_provider: EmbeddingProviderKind = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_threads: int = 4
    model_cache_dir: Path = Path(".cache/models")

    # ---- generation
    llm_provider: LLMProviderKind = "ollama"
    llm_model: str = ""
    """Empty = the provider's default (DEFAULT_MODELS)."""
    llm_base_url: str = "http://localhost:11434/v1"
    """For ollama / openai_compatible (Ollama, vLLM, LM Studio, llama.cpp server)."""
    llm_api_key: str | None = None
    """Bearer token for an openai_compatible server that needs one."""
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(default_factory=list)
    llm_fallback_to_extractive: bool = True
    """If the local model server is unreachable, answer with quoted passages instead of failing (labelled)."""
    llm_timeout_seconds: float = 180.0
    llm_max_tokens: int = 700
    llm_temperature: float = 0.0
    local_only: bool = True
    """Refuse every cloud provider and any OpenAI-compatible URL that is not on this machine or a private network."""
    local_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    require_free_models: bool = True
    """Refuse any OpenRouter model id that does not end in ":free" (requests and the model that answered)."""

    openrouter_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENROUTER_API_KEY"))
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias=AliasChoices("OPENROUTER_BASE_URL")
    )
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("OPENAI_BASE_URL"))

    # ---- connectors (only needed for `clearance sync gdrive|sharepoint`)
    gdrive_folder_id: str = ""
    gdrive_service_account_file: Path | None = None
    gdrive_subject: str = ""
    """Workspace user to impersonate (domain-wide delegation); empty = the service account itself."""
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str | None = None
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""
    sharepoint_organization_domain: str = ""
    """Domain whose principal (see group mapping `domains`) an organization-wide sharing link grants."""

    # ---- budget for real cloud calls (evaluation, judge)
    llm_cache_dir: Path = Path(".cache/llm")
    llm_ledger: Path | None = Path("results/calls.jsonl")
    llm_max_calls: int = 300
    llm_min_seconds_between_requests: float = 3.0
    llm_max_retries: int = 4

    # ---- retrieval and answers
    top_k: int = 5
    min_score: float = 0.5
    """Chunks below this cosine similarity are not given to the model (bge-small scale)."""
    hnsw_iterative_scan: Literal["off", "strict_order", "relaxed_order"] = "strict_order"
    no_answer_policy: NoAnswerPolicy = "generic"
    no_answer_message: str = DEFAULT_NO_ANSWER
    contact_message: str = DEFAULT_CONTACT

    # ---- identity
    auth_mode: Literal["dev", "oidc"] = "dev"
    dev_idp_enabled: bool = True
    """Built-in OIDC issuer for the demo users (discovery, JWKS, RS256 tokens). Never enable in production."""
    dev_idp_issuer: str = "http://localhost:8000/dev-idp"
    dev_idp_key_file: Path = Path(".cache/dev-idp/signing-key.pem")
    token_ttl_seconds: int = 8 * 3600
    oidc_issuer: str = ""
    oidc_audience: str = "clearance"
    oidc_jwks_url: str = ""
    """Empty = read jwks_uri from {issuer}/.well-known/openid-configuration."""
    oidc_algorithms: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["RS256"])
    groups_claim: str = "groups"
    email_claim: str = "email"
    group_mapping_file: Path | None = Path("configs/group-mapping.yaml")
    unmapped_groups: Literal["ignore", "passthrough"] = "ignore"
    admin_principals: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["group:it-admins"])

    # ---- cache, audit, trace
    cache_enabled: bool = True
    cache_max_entries: int = 2000
    cache_ttl_seconds: int = 600
    audit_key: str = ""
    """Secret for the keyed question hash in the audit log. Empty = random per process."""
    audit_excluded_counts: bool = True
    """Record in the (admin-only) audit log how many nearest candidates the user's permissions excluded."""
    trace_show_excluded_total: bool = True
    """Show users how many documents they cannot search (a constant per user, never per question)."""

    # ---- API
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    results_dir: Path = Path("results")
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "CLEARANCE_LOG_LEVEL"))
    log_format: Literal["console", "json"] = Field(
        default="console", validation_alias=AliasChoices("LOG_FORMAT", "CLEARANCE_LOG_FORMAT")
    )

    @field_validator(
        "llm_fallback_models",
        "local_allowed_hosts",
        "oidc_algorithms",
        "admin_principals",
        "cors_origins",
        mode="before",
    )
    @classmethod
    def _split_lists(cls, value: object) -> object:
        return _split(value)

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()
