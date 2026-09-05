"""資料夾外掛：自動偵測（工具／來源／整合）、ENABLED 開關、範例外掛可執行。"""

from __future__ import annotations

import os
import shutil
import textwrap

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.comm import writers
from apps.core.plugins import inventory, load_folder_plugins
from apps.vision import sources
from apps.vision.tools import base
from tests._helpers import blank, run_tool, temp_dir

# AppConfig.ready() 已掃過 plugins/；測試行程若沒走 ready（例如單跑本檔），補掃一次。
load_folder_plugins()


class ExamplePluginTests(SimpleTestCase):
    """出貨的兩個範例外掛（plugins/example_*.py）掛載後可用。"""

    def test_dark_ratio_mounted_and_runs(self):
        self.assertTrue(base.has("dark_ratio"))
        img = blank(value=200)
        img[:, :160] = 10  # 左半全暗 → 比例 0.5
        r = run_tool("dark_ratio", image=img, params={"threshold": 80, "max_ratio": 0.1})
        self.assertEqual(r.status, "ng")
        self.assertEqual(r.branch, "fail")
        self.assertAlmostEqual(r.outputs["ratio"], 0.5, places=2)
        r = run_tool("dark_ratio", image=np.full((100, 100), 200, dtype=np.uint8), params={"threshold": 80, "max_ratio": 0.1})
        self.assertEqual(r.branch, "pass")

    def test_csv_writer_mounted_and_writes(self):
        kinds = {k["kind"]: k for k in writers.kinds()}
        self.assertIn("csv_log", kinds)
        self.assertIn("sample plugin", kinds["csv_log"]["label"])
        self.assertEqual(kinds["csv_log"]["fields"], ["path"])

        folder = temp_dir()
        path = os.path.join(folder, "out.csv")
        try:
            w = writers._resolve_class("csv_log", {})({"path": path}, name="csv")
            w.write({"judge": 1, "width": 12.5})
            w.write({"judge": 0})
            with open(path, encoding="utf-8-sig") as f:
                lines = [line.strip() for line in f if line.strip()]
            self.assertEqual(lines[0], "time,address,value")
            self.assertEqual(len(lines), 4)
            self.assertIn("width", lines[2])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class FolderLoaderTests(SimpleTestCase):
    """掃描指定資料夾：module ENABLED、類別 enabled、三類自動註冊、壞檔不炸。"""

    def setUp(self):
        self.folder = temp_dir()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        for key in ("t_on", "t_off", "t_disabled_mod"):
            base.unregister(key)
        sources._PLUGIN_KINDS.pop("src_x", None)
        writers._PLUGIN_KINDS.pop("wr_x", None)

    def _write(self, name: str, code: str) -> None:
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(code))

    def test_detects_all_three_kinds_and_respects_enabled(self):
        self._write("mixed.py", """
            from apps.comm.writers import Writer
            from apps.vision.sources.grabbers import Grabber
            from apps.vision.tools.base import Result, Tool

            class OnTool(Tool):
                key = "t_on"
                label = "on"
                def execute(self, ctx):
                    return Result(outputs={})

            class OffTool(Tool):
                key = "t_off"
                label = "off"
                enabled = False
                def execute(self, ctx):
                    return Result(outputs={})

            class SrcX(Grabber):
                kind = "src_x"
                label = "來源X"
                def grab(self):
                    return None

            class WrX(Writer):
                kind = "wr_x"
                def _write(self, values):
                    return {"written": len(values)}
        """)
        self._write("disabled_mod.py", """
            ENABLED = False
            from apps.vision.tools.base import Result, Tool

            class DisabledModTool(Tool):
                key = "t_disabled_mod"
                label = "x"
                def execute(self, ctx):
                    return Result(outputs={})
        """)
        self._write("broken.py", "raise RuntimeError('boom')\n")
        self._write("_skipped.py", "raise RuntimeError('不該被 import')\n")

        mounted = load_folder_plugins(self.folder, force=True)
        self.assertEqual(sorted(mounted), ["comm:wr_x", "source:src_x", "tool:t_on"])
        self.assertTrue(base.has("t_on"))
        self.assertFalse(base.has("t_off"))
        self.assertFalse(base.has("t_disabled_mod"))
        self.assertIs(sources._resolve_class("src_x", {}), sources._PLUGIN_KINDS["src_x"])
        self.assertIn("src_x", {k["kind"] for k in sources.kinds()})
        self.assertIn("來源X", {k["label"] for k in sources.kinds()})
        self.assertIs(writers._resolve_class("wr_x", {}), writers._PLUGIN_KINDS["wr_x"])

    def test_duplicate_key_keeps_first(self):
        self._write("dup.py", """
            from apps.vision.tools.base import Result, Tool

            class DupTool(Tool):
                key = "blur"  # 與內建工具同 key → 不覆蓋
                label = "假的模糊"
                def execute(self, ctx):
                    return Result(outputs={})
        """)
        mounted = load_folder_plugins(self.folder, force=True)
        self.assertEqual(mounted, [])
        self.assertNotEqual(base.get("blur").label, "假的模糊")

    def test_missing_folder_is_fine(self):
        self.assertEqual(load_folder_plugins(os.path.join(self.folder, "nope"), force=True), [])

    def test_package_dir_plugin(self):
        """資料夾型外掛：整個專案資料夾丟進來，__init__.py 匯出（或定義）要掛載的類別。"""
        pkg = os.path.join(self.folder, "myproj")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "impl.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent("""
                from apps.vision.tools.base import Result, Tool

                class PkgTool(Tool):
                    key = "t_pkg"
                    label = "pkg"
                    def execute(self, ctx):
                        return Result(outputs={})
            """))
        with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("from .impl import PkgTool\n")
        try:
            mounted = load_folder_plugins(self.folder, force=True)
            self.assertIn("tool:t_pkg", mounted)
            self.assertTrue(base.has("t_pkg"))
        finally:
            base.unregister("t_pkg")

    def test_out_of_tree_folder_gets_package_semantics(self):
        """發行版的外掛資料夾在程式樹外：載入後一樣是 plugins.<name>，資料夾型外掛的相對 import 與 __module__ 判斷成立。"""
        import sys

        from apps.core import plugins as loader

        pkg = os.path.join(self.folder, "outside")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "impl.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent("""
                from apps.vision.tools.base import Result, Tool
                from .helper import LABEL

                class OutTool(Tool):
                    key = "t_outside"
                    label = LABEL
                    def execute(self, ctx):
                        return Result(outputs={})
            """))
        with open(os.path.join(pkg, "helper.py"), "w", encoding="utf-8") as f:
            f.write("LABEL = 'outside'\n")
        with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("from .impl import OutTool\n")
        saved = {n: m for n, m in sys.modules.items() if n == "plugins" or n.startswith("plugins.")}
        try:
            mounted = load_folder_plugins(self.folder, force=True)
            self.assertIn("tool:t_outside", mounted)
            self.assertEqual(sys.modules["plugins.outside"].OutTool.__module__, "plugins.outside.impl")
            self.assertTrue(sys.modules["plugins"].__path__[0].lower().startswith(os.path.realpath(self.folder).lower()))
            self.assertNotIn("_vs_folder_plugin_outside", sys.modules)
            # 換回平台自己的 plugins/ 之後，套件與子模組跟著換（沒有殘留）
            loader._ensure_package(loader.plugin_dir())
            self.assertNotIn("plugins.outside", sys.modules)
        finally:
            base.unregister("t_outside")
            for name in [n for n in sys.modules if n == "plugins" or n.startswith("plugins.")]:
                del sys.modules[name]
            sys.modules.update(saved)

    def test_requirements_hint_uses_this_python(self):
        from apps.core import plugins as loader

        pkg = os.path.join(self.folder, "hinted")
        os.makedirs(pkg)
        open(os.path.join(pkg, "requirements.txt"), "w").close()
        hint = loader._requirements_hint(__import__("pathlib").Path(pkg))
        self.assertIn(__import__("sys").executable, hint)
        self.assertIn("vsctl plugins deps", hint)
        self.assertNotIn("Scripts" + chr(92) + "pip", hint)  # 不再寫死 .venv 的 pip 路徑

    def test_missing_dependency_hint(self):
        """外掛缺依賴：整體不炸、log 提示安裝該外掛的 requirements.txt。"""
        pkg = os.path.join(self.folder, "needs_dep")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("import not_a_real_package_xyz\n")
        with open(os.path.join(pkg, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("not-a-real-package-xyz\n")
        with self.assertLogs("apps.core.plugins", level="ERROR") as captured:
            mounted = load_folder_plugins(self.folder, force=True)
        self.assertEqual(mounted, [])
        joined = "\n".join(captured.output)
        self.assertIn("not_a_real_package_xyz", joined)
        self.assertIn("requirements.txt", joined)


class InventoryTests(SimpleTestCase):
    """外掛頁讀的清單：掛了什麼、停用、錯在哪，都要看得到；重新掃描只碰新檔與失敗的。"""

    def setUp(self):
        self.folder = temp_dir()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def _write(self, name: str, body: str) -> None:
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(body))

    def test_records_ok_disabled_and_error(self):
        self._write("inv_good.py", """
            from apps.vision.tools.base import Param, Result, Tool

            class InvGood(Tool):
                key = "inv_good_tool"
                label = "Inventory good"
                category = "logic"
                params = [Param("x", "x", kind="number", default=1)]
                def execute(self, ctx):
                    return Result(status="ok")
        """)
        self._write("inv_off.py", "ENABLED = False\n")
        self._write("inv_broken.py", "import definitely_not_a_package_xyz\n")
        self._write("inv_broken.requirements.txt", "definitely-not-a-package-xyz\n")
        load_folder_plugins(self.folder, force=True)
        rows = {r["name"]: r for r in inventory()}
        self.assertEqual(rows["inv_good.py"]["status"], "ok")
        self.assertEqual(rows["inv_good.py"]["mounted"], ["tool:inv_good_tool"])
        self.assertEqual(rows["inv_off.py"]["status"], "disabled")
        self.assertEqual(rows["inv_broken.py"]["status"], "error")
        self.assertIn("definitely_not_a_package_xyz", rows["inv_broken.py"]["error"])
        self.assertTrue(rows["inv_broken.py"]["requirements"])
        self.assertIn("pip install", rows["inv_broken.py"]["error"])
        self.assertEqual(rows["inv_good.py"]["kind"], "file")

    def test_rescan_only_touches_new_and_failed(self):
        self._write("inv_first.py", """
            from apps.comm.writers import Writer

            class InvFirst(Writer):
                kind = "inv_first_kind"
                def _write(self, values):
                    return {"written": len(values)}
                def _read(self, addresses):
                    return {}
        """)
        load_folder_plugins(self.folder, force=True)
        self.assertIn("inv_first_kind", {k["kind"] for k in writers.kinds()})
        self._write("inv_second.py", """
            from apps.comm.writers import Writer

            class InvSecond(Writer):
                kind = "inv_second_kind"
                def _write(self, values):
                    return {"written": len(values)}
                def _read(self, addresses):
                    return {}
        """)
        # 第二次掃：只掛新檔，舊檔不重載（沒有重複註冊的警告、清單維持 ok）
        mounted = load_folder_plugins(self.folder, force=True)
        self.assertEqual(mounted, ["comm:inv_second_kind"])
        rows = {r["name"]: r for r in inventory()}
        self.assertEqual(rows["inv_first.py"]["status"], "ok")
        self.assertEqual(rows["inv_second.py"]["mounted"], ["comm:inv_second_kind"])
        # 外掛沒宣告 section 就歸外掛頁
        self.assertEqual({k["kind"]: k["section"] for k in writers.kinds()}["inv_second_kind"], "plugins")


class PluginsCommandTests(SimpleTestCase):
    """manage.py plugins --list：不用伺服器跑也能看外掛掛不掛得起來。"""

    def test_list_json_and_table(self):
        import io as _io
        import json
        import sys

        from django.core.management import call_command

        folder = temp_dir()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "ok_plugin.py"), "w", encoding="utf-8") as f:
            f.write("from apps.vision.tools.base import Result, Tool\nclass CmdTool(Tool):\n    key = 't_cmd'\n    label = 'cmd'\n    def execute(self, ctx):\n        return Result(outputs={})\n")
        with open(os.path.join(folder, "broken.py"), "w", encoding="utf-8") as f:
            f.write("import not_a_real_package_xyz\n")
        saved = {n: m for n, m in sys.modules.items() if n == "plugins" or n.startswith("plugins.")}
        try:
            buf = _io.StringIO()
            call_command("plugins", "--list", "--json", "--dir", folder, stdout=buf)
            out = json.loads(buf.getvalue())
            by_name = {it["name"]: it for it in out["items"]}
            self.assertEqual(by_name["ok_plugin.py"]["status"], "ok")
            self.assertEqual(by_name["ok_plugin.py"]["mounted"], ["tool:t_cmd"])
            self.assertEqual(by_name["broken.py"]["status"], "error")
            buf = _io.StringIO()
            call_command("plugins", "--list", "--dir", folder, stdout=buf)
            self.assertIn("ok_plugin.py", buf.getvalue())
            self.assertIn("FAIL", buf.getvalue())
        finally:
            base.unregister("t_cmd")
            for name in [n for n in sys.modules if n == "plugins" or n.startswith("plugins.")]:
                del sys.modules[name]
            sys.modules.update(saved)


class PluginApiTests(TestCase):
    """外掛頁的 API：清單任何有整合功能的人可讀，重新掃描只有管理員。"""

    def test_list_and_rescan(self):
        r = self.client.get("/api/vision/plugins")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertIn("items", body)
        self.assertTrue(body["dir"])
        self.assertEqual(body["docs_url"], "/docs/plugins.html")
        names = {row["name"] for row in body["items"]}
        self.assertIn("example_dark_ratio.py", names)
        r = self.client.post("/api/vision/plugins/rescan")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("mounted", r.json())
        self.assertEqual(r.json()["mounted"], [])  # 沒有新檔
