from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    app_name: str = "content-intelligence-api"
    redfox_api_key: SecretStr | None = None
    deepseek_key: SecretStr | None = None
    tikhub_api_key: SecretStr | None = None
    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    application_database_url: SecretStr | None = None

    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    local_single_user: bool = False
    secure_cookies: bool = False
    storage_root: Path = Path(__file__).resolve().parents[3] / "data"
    max_file_bytes: int = 50 * 1024 * 1024
    external_media_hosts: list[str] = []
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:16379/0")
    task_queue: str = "cip.tasks.v1"
    task_key_prefix: str = "cip:v1:"


settings = Settings()
