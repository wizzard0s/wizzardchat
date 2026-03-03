"""Application configuration loaded from environment / .env file."""

from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/wizzardfrw"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/wizzardfrw"

    # Auth / JWT
    secret_key: str = "wizzardchat-dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # App
    app_name: str = "WizzardChat"
    app_port: int = 8090

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
