"""全域設定。

所有可調參數集中於此，一律可由環境變數覆寫（見 .env.example）。
不在程式各處散落魔術數字，也不把路徑硬編死——離線部署與 PyInstaller
打包時，路徑解析是最常出錯的地方。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    """回傳專案根目錄。

    PyInstaller 打包後 ``sys._MEIPASS`` 指向解壓縮的臨時目錄，資源檔在那裡；
    但可寫入的資料（DB、日誌）必須放在 exe 旁邊，不能放 _MEIPASS（會被清掉）。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(rel: str) -> Path:
    """解析唯讀資源（web/、docs/）的實際路徑，相容 PyInstaller。"""
    base = Path(getattr(sys, "_MEIPASS", _project_root()))
    return base / rel


def _load_dotenv(path: Path) -> None:
    """極簡 .env 讀取器；不引入額外相依。已存在的環境變數優先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_f(key: str, default: float) -> float:
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default


def _env_i(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    root: Path
    db_path: Path
    host: str
    port: int
    log_level: str
    log_dir: Path

    llm_provider: str
    anthropic_api_key: str
    anthropic_model: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    llm_timeout_s: float

    purity_threshold_ppm: float

    # 預設追蹤的雜質元素。可於匯入資料時擴充。
    elements: tuple[str, ...] = field(default=("Cu", "Fe", "Ni", "Sn"))

    # 殘差學習（L1）護欄：修正量上限為物理預測的 ±20%
    residual_clip_frac: float = 0.20


def load_settings() -> Settings:
    root = _project_root()
    _load_dotenv(root / ".env")

    def _p(key: str, default: str) -> Path:
        raw = Path(_env(key, default))
        return raw if raw.is_absolute() else root / raw

    return Settings(
        root=root,
        db_path=_p("EXPA_DB_PATH", "data/expanalysis.db"),
        host=_env("EXPA_HOST", "127.0.0.1"),
        port=_env_i("EXPA_PORT", 8848),
        log_level=_env("EXPA_LOG_LEVEL", "INFO").upper(),
        log_dir=_p("EXPA_LOG_DIR", "logs"),
        llm_provider=_env("EXPA_LLM_PROVIDER", "anthropic").lower(),
        anthropic_api_key=_env("EXPA_ANTHROPIC_API_KEY", ""),
        anthropic_model=_env("EXPA_ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        openai_api_key=_env("EXPA_OPENAI_API_KEY", ""),
        openai_model=_env("EXPA_OPENAI_MODEL", "gpt-4o"),
        openai_base_url=_env("EXPA_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        llm_timeout_s=_env_f("EXPA_LLM_TIMEOUT_S", 60.0),
        purity_threshold_ppm=_env_f("EXPA_PURITY_THRESHOLD_PPM", 1.0),
    )


SETTINGS = load_settings()
