from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PPE_", extra="ignore")

    env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path(".local/data")
    storage_dir: Path = Path("storage")
    max_upload_bytes: int = 100 * 1024 * 1024
    database_url: str = "sqlite+pysqlite:///.local/data/platform.sqlite3"
    cors_origins: str = "http://localhost:5173"

    def prepare_local_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
