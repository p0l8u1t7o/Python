"""測試共用設定。

每個測試 session 都用獨立的暫存資料庫，不碰開發用的 data/expanalysis.db。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session", autouse=True)
def _isolated_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("expa") / "test.db"
    os.environ["EXPA_DB_PATH"] = str(db)
    os.environ["EXPA_LOG_LEVEL"] = "WARNING"
    os.environ["EXPA_LLM_PROVIDER"] = "template"
    yield db


@pytest.fixture(scope="module")
def seeded_service(_isolated_db):
    """已填入 20 批合成資料的服務實例。"""
    from expanalysis.data.db import get_db
    from expanalysis.data.repository import BatchRepository
    from expanalysis.data.synthetic import SyntheticConfig, seed_database
    from expanalysis.service import AnalysisService

    db = get_db(Path(os.environ["EXPA_DB_PATH"]))
    repo = BatchRepository(db)
    truth = seed_database(repo, SyntheticConfig(n_batches=20))
    svc = AnalysisService(db)
    svc.truth = truth
    return svc
