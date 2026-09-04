"""範例外掛（二）：自訂「整合輸出」（Writer）— 把寫入的值附加到 CSV 檔。

放在 plugins/ 資料夾即自動偵測掛載（重啟後端生效），不用改 .env；
掛載後「連線」頁的 kind 下拉會出現「CSV 紀錄」，config 填 {"path": "D:/logs/results.csv"}。
沒有任何硬體也能完整驗證「流程 → 寫入 Modbus → 連線」的整合路徑。
下面三個變數可直接修改，改顯示名稱／說明／要不要掛載：
"""

from __future__ import annotations

DISPLAY_NAME = "CSV log (sample plugin)"
DESCRIPTION = "Appends every written value to a CSV file (time, address, value)."
ENABLED = True  # False = 這個檔案整個不掛載

import csv  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from typing import Any  # noqa: E402

from apps.comm.writers import CommError, Writer  # noqa: E402
from apps.core.errors import ValidationError  # noqa: E402


class CsvLogWriter(Writer):
    kind = "csv_log"            # 全域唯一；Connection.kind 記這個
    label = DISPLAY_NAME
    description = DESCRIPTION
    enabled = ENABLED           # 也可只停用單一類別
    fields = ["path"]           # 設定頁的 config 欄位提示

    def __init__(self, config: dict[str, Any], **kw: Any) -> None:
        super().__init__(config, **kw)  # 取得 self.timeout、self._lock、計數器
        self.path = str(config.get("path") or "")
        if not self.path:
            raise ValidationError("csv_log requires a path (the full path to the CSV file)", code="comm_config")

    # 只需覆寫 _write／_read／_open／_close；lock、逾時、失敗重試一次都在基底 write()/read()。
    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            fresh = not os.path.exists(self.path)
            # utf-8-sig：Excel 直接開不會亂碼（Windows 中文環境）。
            with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if fresh:
                    writer.writerow(["time", "address", "value"])
                for address, value in values.items():
                    writer.writerow([stamp, address, value])
        except OSError as exc:
            raise CommError(f"CSV write failed: {exc}") from exc
        return {"written": len(values), "path": self.path}

    def info(self) -> dict[str, Any]:
        return {**super().info(), "path": self.path}
