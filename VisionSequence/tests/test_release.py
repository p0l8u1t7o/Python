"""發行樹的合約（scripts/build_release.ps1 的產物）。

沒有設 VS_RELEASE_DIR 就整個 skip；build_release.ps1 自檢階段會設好路徑跑這一支。
鎖住的東西：三層配置需要的檔案、內嵌 Python 的 ._pth（sys.path 不含建置機）、不該出現在客戶端的東西
（tests、frontend/src、.map、樹內的 plugins/）、版本一致、工具與腳本齊全，以及用樹裡的 python 真的能 import 與 manage.py check。
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RELEASE_DIR = os.environ.get("VS_RELEASE_DIR", "").strip()


@unittest.skipUnless(RELEASE_DIR, "VS_RELEASE_DIR not set (built by scripts/build_release.ps1)")
class ReleaseTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = Path(RELEASE_DIR)
        cls.python = cls.tree / "python" / "python.exe"
        cls.release = json.loads((cls.tree / "release.json").read_text(encoding="utf-8"))

    def test_layout_files(self):
        for rel in [
            "python/python.exe", "python/Lib/site-packages", "manage.py", "apps/vision/__init__.py", "config/settings.py",
            "vscapture/protocol.py", "frontend/dist/index.html", "frontend/dist/index.html.gz", "frontend/dist/assets",
            "docs/index.html", "docs/deployment.html", "docs/img", "scripts/vslib.ps1", "scripts/service.ps1", "scripts/proxy.ps1",
            "scripts/vsctl.ps1", "scripts/vsctl.cmd", "scripts/install.ps1", "tools/nssm.exe", "tools/caddy.exe", "tools/vc_redist.x64.exe",
            "tools/LICENSES/README.txt", "examples/plugins/example_dark_ratio.py", "VERSION", "release.json", "README.txt", ".env.example", "requirements.txt",
        ]:
            self.assertTrue((self.tree / rel).exists(), rel)

    def test_nothing_from_the_build_machine(self):
        for rel in ["tests", "frontend/src", "frontend/node_modules", ".venv", "data", "plugins", "logs", ".env", "scripts/dev.ps1", "scripts/bench_tools.py", "scripts/docs_style.py"]:
            self.assertFalse((self.tree / rel).exists(), f"{rel} must not ship")
        self.assertEqual(list((self.tree / "frontend" / "dist").rglob("*.map")), [])
        self.assertEqual(list((self.tree / "apps").rglob("__pycache__")), [])

    def test_pth_pins_sys_path(self):
        pth = next((self.tree / "python").glob("python3*._pth"))
        lines = [ln.strip() for ln in pth.read_text().splitlines() if ln.strip()]
        self.assertIn("..", lines)  # 版本樹根：apps、config
        self.assertIn(r"Lib\site-packages", lines)
        self.assertIn("import site", lines)

    def test_version_consistent(self):
        version = (self.tree / "VERSION").read_text().strip()
        self.assertEqual(self.release["version"], version)
        init = (self.tree / "apps" / "vision" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{version}"', init)
        self.assertEqual(self.release["product"], "VisionSequence")
        self.assertIn("built_at", self.release)

    def test_embedded_python_imports_and_checks(self):
        # 測試行程已載入開發用 .env（DEBUG=1、DATA_DIR=./data…），dotenv 不會覆蓋既有環境變數：子行程要拿乾淨的環境
        dev_keys = {"DEBUG", "DATA_DIR", "DB_PATH", "SECRET_KEY", "ALLOWED_HOSTS", "LOG_LEVEL", "TIME_ZONE", "AUTH_TOKEN_TTL_HOURS",
                    "BEHIND_HTTPS_PROXY", "CORS_ALLOWED_ORIGINS", "VS_HOME", "VS_RELEASE_DIR", "DJANGO_SETTINGS_MODULE"}
        env = {k: v for k, v in os.environ.items() if k not in dev_keys and not k.startswith("VISION_")}
        env.update({"PYTHONIOENCODING": "utf-8", "LOG_LEVEL": "WARNING", "DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONDONTWRITEBYTECODE": "1"})
        with tempfile.TemporaryDirectory() as home:
            env["VS_HOME"] = home
            Path(home, ".env").write_text("DEBUG=0\nSECRET_KEY=release-test-key\nALLOWED_HOSTS=localhost\n", encoding="utf-8")
            out = subprocess.run(
                [str(self.python), "-c", "import sys, cv2, numpy, django, ninja, uvicorn, pymodbus, onnxruntime, whitenoise; "
                 "assert not any('.venv' in p or 'site-packages' in p and 'python' not in p.lower() for p in sys.path), sys.path; print('ok')"],
                cwd=self.tree, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("ok", out.stdout)
            out = subprocess.run([str(self.python), "manage.py", "check"], cwd=self.tree, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            # settings 從 VS_HOME 讀 .env、DATA_DIR 落在 VS_HOME
            out = subprocess.run(
                [str(self.python), "-c", "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); "
                 "from django.conf import settings; print(settings.DEBUG, settings.DATA_DIR, settings.VS_HOME)"],
                cwd=self.tree, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertTrue(out.stdout.startswith("False "), out.stdout)
            self.assertIn(str(Path(home).resolve()), out.stdout)
