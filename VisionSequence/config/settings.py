"""VisionSequence 設定。

全部以環境變數（.env）覆寫；每個參數的意義見 .env.example。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# 發行版的三層配置：<VS_HOME>\app\<ver>\config\settings.py → 客戶資料（.env、data\、plugins\）在 <VS_HOME>，
# 升級只換 app\<ver>。開發時（專案根不叫 app）VS_HOME 就是專案根；環境變數 VS_HOME 可強制指定。
_vs_home = os.environ.get("VS_HOME", "").strip()
VS_HOME = Path(_vs_home).resolve() if _vs_home else (BASE_DIR.parent.parent if BASE_DIR.parent.name == "app" else BASE_DIR)
load_dotenv(VS_HOME / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = _env("SECRET_KEY", "dev-only-secret-change-me")
DEBUG = _env_bool("DEBUG", True)
ALLOWED_HOSTS = [h for h in _env("ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "apps.core",
    "apps.accounts",
    "apps.vision",
    "apps.golden",
    "apps.comm",
]

MIDDLEWARE = [
    # Security 在最外層，靜態檔（whitenoise）的回應也帶安全標頭
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# LAN 上的安全標頭：影像與 SSE 的 URL 帶 ?token=，Referrer-Policy same-origin 不讓它隨連結外流；
# 前端沒有 iframe，X-Frame-Options 直接 SAMEORIGIN。不開 HSTS／SSL redirect：沒憑證的站台要能留在 http。
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = False
X_FRAME_OPTIONS = "SAMEORIGIN"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {},
    }
]

DATA_DIR = Path(_env("DATA_DIR", str(VS_HOME / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
VISION_EXPORT_MAX_MB_KEY = "VISION_EXPORT_MAX_MB"
VISION_EXPORT_MAX_MB = _env_int(VISION_EXPORT_MAX_MB_KEY, 200)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _env("DB_PATH", str(DATA_DIR / "vision.sqlite3")),
        "OPTIONS": {
            # 執行記錄由背景執行緒寫入；WAL 讓讀寫不互鎖。
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;",
        },
        # 測試用檔案型資料庫：記憶體共享快取的 SQLite 對跨執行緒（執行緒池、背景寫入）
        # 會回 "database table is locked"，檔案 + WAL 才是正式環境的行為。
        "TEST": {"NAME": str(DATA_DIR / "test.sqlite3")},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "zh-hant"
TIME_ZONE = _env("TIME_ZONE", "Asia/Taipei")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# 前端 build 產物由 whitenoise 掛在 /（不是 /static/，index.html 引用的是 /assets/*）：hashed 的 /assets/* 給一年 immutable、
# index.html 每次重新驗證、build 預壓的 .gz／.br 自動選用；深連結（/flows/3）不是檔案 → 落到 urls 的 _spa 回 index.html。
# 每台客戶端電腦只下載一次 2.7 MB 的 JS，之後全是 304／快取，不再經過 Django 的 view。
WHITENOISE_ROOT = str(FRONTEND_DIST) if FRONTEND_DIST.exists() else None
WHITENOISE_INDEX_FILE = True
WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: url.startswith("/assets/")  # noqa: E731 - whitenoise 要的是可呼叫物件


def _static_headers(headers, path, url):
    if url in ("/", "/index.html"):
        headers["Cache-Control"] = "no-cache"


WHITENOISE_ADD_HEADERS_FUNCTION = _static_headers

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [o for o in _env("CORS_ALLOWED_ORIGINS", "").split(",") if o]

# 前面有 HTTPS 反向代理（Caddy／nginx）時：相信代理的 X-Forwarded-Proto／Host，request.scheme 才會是 https。
BEHIND_HTTPS_PROXY = _env_bool("BEHIND_HTTPS_PROXY", False)
if BEHIND_HTTPS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# ---------------------------------------------------------------------------
# 視覺引擎
# ---------------------------------------------------------------------------
VISION = {
    # 同時執行的檢測流程上限（執行緒池大小）。每個流程一次只跑一個 run，
    # 所以這也是「同時忙碌的流程數」。可用 .env 擴充。
    "MAX_WORKERS": _env_int("VISION_MAX_WORKERS", 10),
    # 同一流程的 run 排隊上限；超過即拒絕（回 429），不無限堆積。
    "MAX_QUEUE_PER_FLOW": _env_int("VISION_MAX_QUEUE_PER_FLOW", 16),
    # 單一 run 的牆鐘上限（秒）；超過標 failed。
    "RUN_TIMEOUT_S": _env_float("VISION_RUN_TIMEOUT_S", 30.0),
    # 伺服器啟動後的靜默暖機: off | commissioned | all. 預設關閉, 避免改變既有站台啟動行為.
    "WARMUP": _env("VISION_WARMUP", "off"),
    # 每條暖機流程的上限秒數.
    "WARMUP_TIMEOUT_S": _env_float("VISION_WARMUP_TIMEOUT_S", 30.0),
    # 逗號分隔的流程 id 清單; 空值時依 VISION_WARMUP 規則選擇.
    "WARMUP_FLOWS": _env("VISION_WARMUP_FLOWS", ""),
    # 每個流程在記憶體保留幾次 run 的影像（供前端檢視）。
    "KEEP_RUN_IMAGES": _env_int("VISION_KEEP_RUN_IMAGES", 8),
    # 影像封存（出貨預設不存；各流程自己開，見 apps/vision/archive.py）
    "ARCHIVE_DEFAULT": _env("VISION_ARCHIVE_DEFAULT", "off"),   # off | ng | all
    "ARCHIVE_DAYS": _env_int("VISION_ARCHIVE_DAYS", 90),
    "ARCHIVE_MAX_GB": _env_float("VISION_ARCHIVE_MAX_GB", 20.0),
    "ARCHIVE_DIR": _env("VISION_ARCHIVE_DIR", ""),
    # 使用者設定的 CSV/TXT 與影像輸出，預設在 DATA_DIR/file_outputs。
    "FILE_OUTPUT_DIR": _env("VISION_FILE_OUTPUT_DIR", ""),
    "FILE_OUTPUT_DAYS": _env_int("VISION_FILE_OUTPUT_DAYS", 90),
    "FILE_OUTPUT_MAX_GB": _env_float("VISION_FILE_OUTPUT_MAX_GB", 20.0),
    "FILE_OUTPUT_QUEUE": _env_int("VISION_FILE_OUTPUT_QUEUE", 1000),
    # 影像快取總量上限（MB）。
    "IMAGE_CACHE_MB": _env_int("VISION_IMAGE_CACHE_MB", 1024),
    # 是否把每次 run 寫進資料庫（背景執行緒批次寫）。高速產線可關閉只留統計。
    "PERSIST_RUNS": _env_bool("VISION_PERSIST_RUNS", True),
    #: 持久化執行緒閒置時做資料保留整理（測試會關掉）
    "RETENTION_SWEEP": _env_bool("VISION_RETENTION_SWEEP", True),
    # 資料庫保留的 run 記錄上限（每流程）。
    # 明細保留天數為主、筆數為輔；每小時彙總（FlowRunHourly）永久保留
    "KEEP_RUN_DAYS": _env_int("VISION_KEEP_RUN_DAYS", 365),
    "KEEP_RUN_ROWS": _env_int("VISION_KEEP_RUN_ROWS", 20000),
    # 量測值 SPC：具名數值輸出另存 MeasurementLog（保留天數獨立於明細；0＝永久）
    "MEASUREMENT_LOG": _env_bool("VISION_MEASUREMENT_LOG", True),
    "MEASUREMENT_DAYS": _env_int("VISION_MEASUREMENT_DAYS", 365),
    "KEEP_VERSIONS": _env_int("VISION_KEEP_VERSIONS", 50),
    "AUDIT_DAYS": _env_int("VISION_AUDIT_DAYS", 365),
    #: 備份 zip 與還原前資料庫副本各保留幾份（0＝全部保留）
    "KEEP_BACKUPS": _env_int("VISION_KEEP_BACKUPS", 10),
    #: 維護視窗：這個整點（當地時間）才做備份整理與 SQLite 空間回收
    "MAINTENANCE_HOUR": _env_int("VISION_MAINTENANCE_HOUR", 3),
    # 資料夾外掛：這個資料夾下的 .py 啟動時自動掛載（繼承 Tool／Grabber／Writer 即可，不用改 .env）。
    "PLUGIN_DIR": Path(_env("VISION_PLUGIN_DIR", str(VS_HOME / "plugins"))),
    # 外掛工具模組（逗號分隔的 python 模組路徑），啟動時 import；模組內呼叫 register()。
    "TOOL_PLUGINS": [m.strip() for m in _env("VISION_TOOL_PLUGINS", "").split(",") if m.strip()],
    # 影像來源外掛（kind -> "module:Class"），例如 GigE SDK 的封裝。
    "SOURCE_PLUGINS": dict(
        item.split("=", 1) for item in _env("VISION_SOURCE_PLUGINS", "").split(",") if "=" in item
    ),
    # 通訊連線外掛（kind -> "module:Class"），例如 OPC UA 的 Writer。
    "COMM_PLUGINS": dict(
        item.split("=", 1) for item in _env("VISION_COMM_PLUGINS", "").split(",") if "=" in item
    ),
    # 圖大小上限。
    "MAX_NODES": _env_int("VISION_MAX_NODES", 300),
    "MAX_EDGES": _env_int("VISION_MAX_EDGES", 600),
    # 傳給前端的預覽影像最長邊預設值。
    "PREVIEW_MAX_SIDE": _env_int("VISION_PREVIEW_MAX_SIDE", 1600),
    # 範本影像 / 模型等資產存放處。
    "ASSET_DIR": Path(_env("VISION_ASSET_DIR", str(DATA_DIR / "assets"))),
    # 選填 API 金鑰；設定後所有 /api 要帶 X-API-Key。
    "API_KEY": _env("VISION_API_KEY", ""),
    # 深度學習教導：智慧選取／全圖提案用的 SAM 權重（ultralytics 官方名稱或 .pt 路徑；sam2.1_t 約 150MB、mobile_sam 約 40MB）
    "SAM_MODEL": _env("VISION_SAM_MODEL", "sam2.1_t.pt"),
    # OpenCV 執行緒數；0 = 交給 OpenCV 自己決定。多流程並行時建議 1～2，避免互搶。
    "CV_THREADS": _env_int("VISION_CV_THREADS", 2),
    # 前處理加速（WP-16）：auto｜cpu｜opencl｜cuda；只有 remap／medianBlur／filter2D／dft 在影像 ≥ ACCEL_MIN_PIXELS 時走 GPU（見 docs/performance.html §5.7o）
    "ACCEL": _env("VISION_ACCEL", "auto"),
    "ACCEL_MIN_PIXELS": _env_int("VISION_ACCEL_MIN_PIXELS", 4_000_000),
    # 站台識別：寫進每筆 run、回傳與事件（多站匯總用）。
    "STATION_ID": _env("VISION_STATION_ID", "ST01"),
    # HTTP 埠（manage.py serve 的預設；doctor 也探這個埠）。
    "HTTP_PORT": _env_int("VISION_HTTP_PORT", 8000),
    # TCP 自動化介面（manage.py serve 一起啟動）。
    "TCP_HOST": _env("VISION_TCP_HOST", "0.0.0.0"),
    "TCP_PORT": _env_int("VISION_TCP_PORT", 9000),
    # TCP 介面金鑰：非空時連線要先送 AUTH <key>（PING 除外）；空＝不驗證（相容舊設備，靠防火牆）。
    "TCP_AUTH": _env("VISION_TCP_AUTH", ""),
    # SSE 事件串流同時連線上限（每個開著的瀏覽器分頁一條）；超過回 503 讓瀏覽器稍後重試。
    "SSE_MAX_STREAMS": _env_int("VISION_SSE_MAX_STREAMS", 64),
    # 擷取端（相機電腦上的擷取程式，vscapture）連入的監聽位址／埠；同機走共享記憶體、跨機走 TCP（manage.py serve 隨 TCP 介面一起啟動）。
    "CAPTURE_HOST": _env("VISION_CAPTURE_HOST", "0.0.0.0"),
    "CAPTURE_PORT": _env_int("VISION_CAPTURE_PORT", 9100),
    # 擷取端單張影像上限（MB）；超過即斷線。
    "CAPTURE_MAX_FRAME_MB": _env_int("VISION_CAPTURE_MAX_FRAME_MB", 128),
    # 擷取端登錄金鑰；空＝沿用 VISION_API_KEY（兩者皆空則不驗證）。
    "CAPTURE_AUTH": _env("VISION_CAPTURE_AUTH", ""),
    # 「擷取端相機」來源依需求取像的預設逾時（毫秒）。
    "CAPTURE_TIMEOUT_MS": _env_int("VISION_CAPTURE_TIMEOUT_MS", 1000),
    # AI 助手（apps/vision/agent）：設定金鑰＋安裝 anthropic 才啟用 LLM 生成；
    # 沒設定時規則引擎完全離線可用。影像會縮圖後送到 LLM 供應商，內網環境請留空。
    "AGENT_PROVIDER": _env("VISION_AGENT_PROVIDER", ""),  # offline | claude | openai | gemini；空＝有金鑰就 claude
    "AGENT_API_KEY": _env("VISION_AGENT_API_KEY", ""),
    "AGENT_MODEL": _env("VISION_AGENT_MODEL", ""),  # 空＝各供應商預設（claude-opus-5 / gpt-4o / gemini-3.6-flash）
    "AGENT_BASE_URL": _env("VISION_AGENT_BASE_URL", ""),  # openai_compatible 本地端點，例如 http://127.0.0.1:11434/v1
    "AGENT_TIMEOUT_S": _env("VISION_AGENT_TIMEOUT_S", "120"),  # LLM 生成逾時（秒）；本地模型慢可拉長
    "AGENT_MODE": _env("VISION_AGENT_MODE", "single"),  # single（一次生成）| agentic（代理迴圈：試跑→修→驗證，背景工作＋步驟時間軸）
    "AGENT_HELP_LOOKUPS": _env("VISION_AGENT_HELP_LOOKUPS", "1"),  # 問答路徑的唯讀即時查詢（0＝關）
    # 批次測試：一個影像集最多幾張、每流程保留幾個影像集、每影像集保留幾次執行、同時執行的批次數
    "BATCH_MAX_IMAGES": _env_int("VISION_BATCH_MAX_IMAGES", 200),
    "KEEP_BATCH_SETS": _env_int("VISION_KEEP_BATCH_SETS", 10),
    "KEEP_BATCH_RUNS": _env_int("VISION_KEEP_BATCH_RUNS", 20),
    "BATCH_MAX_RUNNING": _env_int("VISION_BATCH_MAX_RUNNING", 2),
}
VISION["ASSET_DIR"].mkdir(parents=True, exist_ok=True)

#: 測試時把資產目錄換到系統暫存區（測試寫的固定影像／模型／封存不該留在站台的 datassets）
TEST_RUNNER = "config.testrunner.VisionTestRunner"

# 使用者權杖有效期（小時）。
AUTH_TOKEN_TTL_HOURS = _env_int("AUTH_TOKEN_TTL_HOURS", 24 * 14)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": _env("LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}},
}
