from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_api_key: str = ""
    gemini_ceo_model: str = "gemini-3.5-flash-lite"
    gemini_agent_model: str = "gemini-3.5-flash-lite"
    gemini_judge_model: str = "gemini-2.5-flash-lite"
    llm_requests_per_second: float = 0.22
    llm_max_concurrency: int = 2
    llm_max_retries: int = 4
    llm_timeout_seconds: float = 120.0

    # Judge (independent evaluation). Groq by default; it must differ from the agent model.
    groq_api_key: str = ""
    judge_provider: str = "groq"  # "groq" | "gemini" (uses gemini_judge_model)
    groq_judge_model: str = "openai/gpt-oss-120b"
    judge_tokens_per_minute: int = 7000  # Groq free tier allows 8000 TPM; keep headroom
    judge_max_retries: int = 4

    # Self-evaluation in live requests
    eval_recovery: str = "retry"  # "retry": re-run an agent once with judge feedback | "observe"
    eval_max_retries: int = 1
    eval_judge_enabled: bool = True

    # Offline eval harness
    evals_dir: str = "./data/evals"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )

    github_token: str = ""
    github_owner: str = ""
    github_cache_ttl_seconds: int = 900
    github_api_url: str = "https://api.github.com"

    database_url: str = "sqlite:///./data/org.db"
    checkpoint_db_path: str = "./data/checkpoints.db"
    seed: int = 42
    seed_max_repos: int = 12
    currency: str = "INR"

    max_peer_hops: int = 2
    max_peer_calls_per_agent: int = 3
    graph_recursion_limit: int = 40

    log_level: str = "INFO"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
