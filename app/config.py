"""Application configuration loaded from environment / .env file."""

import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_DEV_SECRET = "wizzardchat-dev-secret-key-change-in-production"
_DEV_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/wizzardfrw"

_log = logging.getLogger("config")


class Settings(BaseSettings):
    # Database
    database_url: str = _DEV_DB_URL
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/wizzardfrw"
    db_schema: str = "chat"  # override via DB_SCHEMA in .env — e.g. "chat_acme", "chat_beta"

    # Auth / JWT
    secret_key: str = _DEV_SECRET
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 6000

    # Admin bootstrap
    # Set ADMIN_INITIAL_PASSWORD in .env to seed the admin on first boot.
    # Leave empty to skip seeding (for environments where admin already exists).
    admin_initial_password: str = ""

    # CORS
    # Comma-separated list of allowed origins for the browser UI.
    # Set CORS_ORIGINS in .env. Use "*" only for pure public APIs (no credentials).
    cors_origins: str = "http://localhost:8090,http://localhost:3099,http://127.0.0.1:8090"

    # WizzardAI integration
    wizzardai_base_url: str = "http://127.0.0.1:8080"
    wizzardai_api_key: str = ""

    # LibreTranslate (self-hostable, free)
    # Run locally: docker run -p 5000:5000 libretranslate/libretranslate
    libretranslate_url: str = "http://localhost:5000"
    libretranslate_api_key: str = ""  # leave blank unless your instance requires one

    # WizzardQA integration
    wizzardqa_webhook_url: str = "http://127.0.0.1:8093/api/v1/webhooks/interaction-closed"
    wizzardqa_integration_key: str = ""  # shared trust key — must match INTEGRATION_TRUST_KEY in WizzardQA
    wizzardqa_enabled: bool = True

    # WizzardWFM integration
    wizzardwfm_integration_key: str = ""  # shared trust key — must match INTEGRATION_TRUST_KEY in WizzardWFM

    # App
    app_name: str = "WizzardChat"
    app_port: int = 8090

    # ── Call Recording Storage ──────────────────────────────────────────────
    # Set RECORDING_STORAGE=s3 to store recordings in S3 / Wasabi instead of
    # (or in addition to) the local wizzrecordings/ folder.
    # When set to "local" (default) files are written to wizzrecordings/.
    # When set to "s3"  files are uploaded to S3/Wasabi AND a local cache copy
    # is kept; set RECORDING_LOCAL_CACHE=false to skip the local cache.
    recording_storage: str = "local"       # "local" | "s3"
    recording_local_cache: bool = True      # keep local copy even when storage=s3

    # S3 / Wasabi — both use the same boto3 code path.
    # Wasabi endpoints:  s3.wasabisys.com  (us-east-1)
    #                    s3.eu-central-1.wasabisys.com  (eu-central-1)
    # AWS S3: leave recording_s3_endpoint_url blank.
    recording_s3_bucket: str = ""
    recording_s3_prefix: str = "wizzrecordings"  # key prefix inside the bucket
    recording_s3_access_key: str = ""
    recording_s3_secret_key: str = ""
    recording_s3_region: str = "us-east-1"
    recording_s3_endpoint_url: str = ""     # blank = AWS S3; set for Wasabi/MinIO
    recording_s3_presign_ttl: int = 3600    # seconds for presigned playback URLs

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}

    def warn_insecure_defaults(self) -> None:
        """Log prominent warnings when running with known-insecure dev defaults."""
        if self.secret_key == _DEV_SECRET:
            _log.warning(
                "SECURITY: JWT secret_key is the dev default. "
                "Set SECRET_KEY in your .env file before going to production."
            )
        if self.database_url == _DEV_DB_URL:
            _log.warning(
                "SECURITY: database_url is the dev default (postgres/postgres). "
                "Set DATABASE_URL in your .env file for production."
            )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
