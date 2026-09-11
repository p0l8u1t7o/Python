"""測試用的 runner：把資產目錄指到系統暫存區，並在每個測試之間清掉背景寫回的殘留。

測試會真的寫檔（固定影像、模型資產、封存影像），以前全部落在站台的 `data/assets/`，
跑完就留下一堆沒人引用的孤兒。這裡在整個測試工作階段換掉 `VISION["ASSET_DIR"]`，
但用**固定路徑**（不是每次一個新資料夾），所以深度學習底模這種下載一次就好的東西還是有快取。

背景持久化執行緒（`runner.persister`）每 2 秒把流程變數寫回資料庫、並寫入排隊中的執行報告。
變數存放區與佇列都是整個行程共用的一份，前一個測試留下的髒鍵或報告會在**下一個測試**執行時才寫回：
碰到 SimpleTestCase 就是 DatabaseOperationForbidden，流程已被刪掉就是 FOREIGN KEY 失敗。
測試結果不受影響，但每次全套的日誌都有十幾筆假錯誤，會淹掉真正的問題。
所以每個測試結束時丟掉這些殘留——與各測試自己在 setUp 呼叫 `variables.store.clear()` 是同一件事，
只是統一由 runner 做，不必每個檔案記得。產品程式與熱路徑行為不變。
"""

from __future__ import annotations

import queue
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

#: 每台機器一個固定位置：`%TEMP%/visionsequence-test-assets`
#: `Path`（不是 str）：設定裡本來就是 Path，測試會用 `.parent` 之類的屬性
TEST_ASSET_DIR = Path(tempfile.gettempdir()) / "visionsequence-test-assets"


def reset_background_state() -> None:
    """丟掉還沒寫回的流程變數與排隊中的執行報告（只給測試用）。"""
    from apps.vision import variables
    from apps.vision.runner import persister

    variables.store.clear()
    while True:
        try:
            item = persister.q.get_nowait()
        except queue.Empty:
            break
        if item is None:  # 停止訊號要留著
            persister.q.put_nowait(None)
            break


class _IsolatingResult:
    def stopTest(self, test):  # noqa: N802（unittest 的命名）
        try:
            reset_background_state()
        finally:
            super().stopTest(test)


class VisionTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        TEST_ASSET_DIR.mkdir(parents=True, exist_ok=True)
        self._assets = override_settings(VISION={**settings.VISION, "ASSET_DIR": TEST_ASSET_DIR})
        self._assets.enable()

    def teardown_test_environment(self, **kwargs):
        try:
            self._assets.disable()
        finally:
            super().teardown_test_environment(**kwargs)

    def get_resultclass(self):
        # --pdb／--debug-sql 會給自己的 result 類別，疊在它上面而不是取代它
        base = super().get_resultclass() or unittest.TextTestResult
        return type("VisionTestResult", (_IsolatingResult, base), {})
