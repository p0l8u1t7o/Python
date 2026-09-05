"""設定檔的部署行為：VS_HOME 三層配置偵測（app\\<ver>\\config → 上兩層）、環境變數覆寫、壞值不讓伺服器起不來、新設定鍵有預設。

settings.py 只依賴 os／pathlib／dotenv，所以用 runpy 在暫存樹裡獨立執行，不碰目前這個 Django 行程的設定。"""

from __future__ import annotations

import os
import runpy
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

SETTINGS_SRC = Path(settings.BASE_DIR) / "config" / "settings.py"


def _run(settings_path: Path, env: dict[str, str]) -> dict:
    """以指定環境變數執行一份 settings.py，回傳它的全域變數。"""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("VISION_", "VS_HOME", "DATA_DIR", "DB_PATH", "BEHIND_HTTPS_PROXY", "DEBUG", "SECRET_KEY", "ALLOWED_HOSTS"))}
    with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
        return runpy.run_path(str(settings_path))


class SettingsLayoutTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _copy_to(self, rel: str) -> Path:
        tree = self.tmp / rel
        tree.mkdir(parents=True)
        shutil.copy2(SETTINGS_SRC, tree / "settings.py")
        return tree / "settings.py"

    def test_dev_layout_uses_the_project_root(self):
        # <proj>\config\settings.py（上層不叫 app）→ VS_HOME＝專案根（沒有 .env 也一樣）
        ns = _run(self._copy_to("proj/config"), {})
        root = (self.tmp / "proj").resolve()
        self.assertEqual(ns["VS_HOME"], root)
        self.assertEqual(ns["DATA_DIR"], root / "data")
        self.assertEqual(ns["VISION"]["PLUGIN_DIR"], root / "plugins")

    def test_release_layout_puts_customer_data_two_levels_up(self):
        # <home>\app\1.2.3\config\settings.py → VS_HOME=<home>、data／plugins／.env 都在 <home>
        home = self.tmp / "home"
        tree = home / "app" / "1.2.3" / "config"
        tree.mkdir(parents=True)
        shutil.copy2(SETTINGS_SRC, tree / "settings.py")
        (home / ".env").write_text("VISION_STATION_ID=FROM_HOME_ENV\n", encoding="utf-8")
        ns = _run(tree / "settings.py", {})
        self.assertEqual(ns["VS_HOME"], home.resolve())
        self.assertEqual(ns["DATA_DIR"], home.resolve() / "data")
        self.assertEqual(ns["VISION"]["PLUGIN_DIR"], home.resolve() / "plugins")
        self.assertEqual(ns["VISION"]["STATION_ID"], "FROM_HOME_ENV")
        self.assertTrue((home / "data").is_dir(), "DATA_DIR 會在設定載入時建立")

    def test_vs_home_env_overrides_detection(self):
        home = self.tmp / "elsewhere"
        home.mkdir()
        ns = _run(SETTINGS_SRC, {"VS_HOME": str(home)})
        self.assertEqual(ns["VS_HOME"], home.resolve())
        self.assertEqual(ns["DATA_DIR"], home.resolve() / "data")
        # 明確的 DATA_DIR／VISION_PLUGIN_DIR 仍優先
        ns = _run(SETTINGS_SRC, {"VS_HOME": str(home), "DATA_DIR": str(self.tmp / "d"), "VISION_PLUGIN_DIR": str(self.tmp / "p")})
        self.assertEqual(ns["DATA_DIR"], self.tmp / "d")
        self.assertEqual(ns["VISION"]["PLUGIN_DIR"], self.tmp / "p")

    def test_bad_values_fall_back_instead_of_crashing(self):
        ns = _run(SETTINGS_SRC, {"VS_HOME": str(self.tmp), "VISION_RUN_TIMEOUT_S": "abc", "VISION_HTTP_PORT": "eighty", "VISION_SSE_MAX_STREAMS": ""})
        self.assertEqual(ns["VISION"]["RUN_TIMEOUT_S"], 30.0)
        self.assertEqual(ns["VISION"]["HTTP_PORT"], 8000)
        self.assertEqual(ns["VISION"]["SSE_MAX_STREAMS"], 64)

    def test_new_deployment_keys(self):
        ns = _run(SETTINGS_SRC, {"VS_HOME": str(self.tmp)})
        self.assertEqual(ns["VISION"]["TCP_AUTH"], "")
        self.assertFalse(ns["BEHIND_HTTPS_PROXY"])
        self.assertNotIn("SECURE_PROXY_SSL_HEADER", ns)
        ns = _run(SETTINGS_SRC, {"VS_HOME": str(self.tmp), "BEHIND_HTTPS_PROXY": "1", "VISION_TCP_AUTH": "k", "VISION_HTTP_PORT": "8443"})
        self.assertTrue(ns["BEHIND_HTTPS_PROXY"])
        self.assertEqual(ns["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertTrue(ns["USE_X_FORWARDED_HOST"])
        self.assertEqual(ns["VISION"]["TCP_AUTH"], "k")
        self.assertEqual(ns["VISION"]["HTTP_PORT"], 8443)

    def test_env_example_covers_every_vision_key(self):
        # .env.example 是設定的說明書：settings.py 讀的每個 VISION_* 鍵都要在裡面（少一個就是文件漏了）
        import re

        src = SETTINGS_SRC.read_text(encoding="utf-8")
        keys = set(re.findall(r'_env(?:_int|_float|_bool)?\("(VISION_[A-Z_]+)"', src))
        example = (Path(settings.BASE_DIR) / ".env.example").read_text(encoding="utf-8")
        missing = sorted(k for k in keys if f"\n{k}=" not in example)
        self.assertEqual(missing, [], f".env.example 缺少：{missing}")
        for key in ("DB_PATH", "AUTH_TOKEN_TTL_HOURS", "BEHIND_HTTPS_PROXY", "DATA_DIR"):
            self.assertIn(f"\n{key}=", example)
