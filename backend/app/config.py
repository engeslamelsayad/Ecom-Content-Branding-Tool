"""Application settings, all sourced from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    # No signing secret: a session cookie carries an opaque random token that is
    # looked up in the sessions table, not signed application state. There is no
    # shared secret to leak, and logout revokes the row immediately.
    app_name: str = "Ecom Content & Branding Tool"
    database_url: str = "sqlite+aiosqlite:///./local.db"

    # --- Anthropic ---
    anthropic_api_key: str = ""
    model_deep: str = "claude-opus-5"
    model_fast: str = "claude-sonnet-5"
    # Server-side refusal fallback (recommended default for opus-5 code).
    # Disabled automatically at runtime if the account lacks the beta.
    enable_refusal_fallback: bool = True

    # --- Seed owner account (created on first boot only) ---
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme123"
    admin_name: str = "Owner"

    # --- Storage ---
    # On Railway this must point at a mounted Volume; the container disk is ephemeral.
    storage_dir: Path = REPO_ROOT / "storage"
    skills_dir: Path = REPO_ROOT

    # --- Limits ---
    max_upload_mb: int = 200
    video_max_frames: int = 12
    session_days: int = 30
    fal_key: str = ""
    openai_api_key: str = ""
    higgsfield_key: str = ""
    connection_encryption_key: str = ""
    max_concurrent_runs: int = 3
    production_daily_limit: int = 30
    production_max_active: int = 2
    production_poll_seconds: float = 5.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Railway hands out postgres:// ; SQLAlchemy needs the asyncpg driver spelled out.
    if s.database_url.startswith("postgres://"):
        s.database_url = s.database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif s.database_url.startswith("postgresql://"):
        s.database_url = s.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
