"""測試用的 runner：把資產目錄指到系統暫存區。

測試會真的寫檔（固定影像、模型資產、封存影像），以前全部落在站台的 `data/assets/`，
跑完就留下一堆沒人引用的孤兒。這裡在整個測試工作階段換掉 `VISION["ASSET_DIR"]`，
但用**固定路徑**（不是每次一個新資料夾），所以深度學習底模這種下載一次就好的東西還是有快取。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

#: 每台機器一個固定位置：`%TEMP%/visionsequence-test-assets`
#: `Path`（不是 str）：設定裡本來就是 Path，測試會用 `.parent` 之類的屬性
TEST_ASSET_DIR = Path(tempfile.gettempdir()) / "visionsequence-test-assets"


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
