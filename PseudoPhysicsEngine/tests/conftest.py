from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from ppe_api import create_app


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'test.sqlite3').as_posix()}"


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def client(database_url: str, storage_dir: Path) -> Iterator[TestClient]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    with TestClient(create_app(database_url=database_url, storage_dir=storage_dir)) as test_client:
        yield test_client
