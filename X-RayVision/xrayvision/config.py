"""
執行設定：資料夾位置、服務位址、分析資源

設定檔為資料根目錄下的 settings.json (不存在時使用預設值)：
{
  "host": "127.0.0.1", "port": 8600,
  "workers": 0,                 分析行程數，0 = 一半的處理器核心
  "archive_originals": true,    原始影像複製封存 (可追溯與重新分析)
  "watch_interval_s": 5
}
"""
import json
import os
from dataclasses import asdict, dataclass, field

DEFAULT_DATA_DIR = os.environ.get("XRAYVISION_DATA", os.path.join(os.getcwd(), "data_xrv"))


@dataclass
class Settings:
    data_dir: str = DEFAULT_DATA_DIR
    host: str = "127.0.0.1"             # 只綁定本機
    port: int = 8600
    workers: int = 0
    archive_originals: bool = True
    watch_interval_s: float = 5.0
    extra: dict = field(default_factory=dict)

    # 衍生路徑
    @property
    def db_path(self):
        return os.path.join(self.data_dir, "xrayvision.db")

    @property
    def archive_dir(self):
        return os.path.join(self.data_dir, "archive")

    @property
    def results_dir(self):
        return os.path.join(self.data_dir, "results")

    @property
    def calibration_dir(self):
        return os.path.join(self.data_dir, "calibration")

    @property
    def logs_dir(self):
        return os.path.join(self.data_dir, "logs")

    @property
    def exports_dir(self):
        return os.path.join(self.data_dir, "exports")

    @property
    def uploads_dir(self):
        return os.path.join(self.data_dir, "uploads")

    @property
    def models_dir(self):
        return os.path.join(self.data_dir, "models")

    def ensure_dirs(self):
        for d in (self.data_dir, self.archive_dir, self.results_dir, self.calibration_dir, self.logs_dir,
                  self.exports_dir, self.uploads_dir, self.models_dir):
            os.makedirs(d, exist_ok=True)

    @classmethod
    def load(cls, data_dir=None):
        data_dir = os.path.abspath(data_dir or DEFAULT_DATA_DIR)
        s = cls(data_dir=data_dir)
        p = os.path.join(data_dir, "settings.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            known = {k for k in asdict(s) if k not in ("data_dir", "extra")}
            for k, v in d.items():
                if k in known:
                    setattr(s, k, v)
                else:
                    s.extra[k] = v
        return s
