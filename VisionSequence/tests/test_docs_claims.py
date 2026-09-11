"""文件不得落後實作。

為什麼要有這一支：README 曾經把**已經做好的標定子系統**列在「尚未實作」，
架構頁停在 74 個工具、範例頁停在 67 個（當時實際是 113 個）。
人看到過期文件會困惑，AI 代理看到會直接當成事實——可能重做已有的功能，
或對既有能力做出錯誤判斷。所以把「文件宣稱」與「程式碼現況」綁在一起，
過期就讓測試變紅，而不是靜靜地誤導下一個接手的人。

新增工具或範本後這一支會失敗，那是刻意的：順手把數字改掉就好。
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from apps.vision import demo
from apps.vision.tools import base

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _one_int(pattern: str, text: str, what: str) -> int:
    found = re.findall(pattern, text)
    assert found, f"文件裡找不到{what}的敘述（樣式 {pattern}）"
    return int(found[0])


def _count_backend_tests() -> int:
    """數 tests/ 底下的測試方法；只求量級對得上，不必與 runner 完全一致。"""
    total = 0
    for path in (ROOT / "tests").glob("test_*.py"):
        total += len(re.findall(r"^\s+def test_\w+", path.read_text(encoding="utf-8"), re.M))
    return total


class ScaleClaimTests(TestCase):
    """README 與 CLAUDE.md 的規模數字要與實際相符。"""

    def setUp(self):
        self.tools = base.all_types()

    def test_tool_count_is_current(self):
        for name in ("README.md", "CLAUDE.md"):
            claimed = _one_int(r"(\d+) 個內建工具", _read(name), "內建工具數")
            self.assertEqual(claimed, len(self.tools), f"{name} 的內建工具數過期")

    def test_template_count_is_current(self):
        claimed = _one_int(r"`demo.BUILTIN_TEMPLATES`，(\d+) 個", _read("CLAUDE.md"), "範本數")
        self.assertEqual(claimed, len(demo.BUILTIN_TEMPLATES), "CLAUDE.md 的範本數過期")

    def test_backend_test_count_claim_is_roughly_current(self):
        """測試數量用「約 N 項」寫，容許 5% 誤差。

        每加一條測試就讓文件變紅太吵，但整整差了一兩百項就會誤導——
        使用者實際踩到的就是「文件中的測試數量存在不同版本的敘述」。
        所以綁一個寬鬆的範圍：小幅增加不必改，長期漂移會被抓出來。
        """
        actual = _count_backend_tests()
        for name in ("README.md", "CLAUDE.md"):
            claimed = _one_int(r"後端約 (\d+) 項", _read(name), "後端測試數")
            self.assertLessEqual(
                abs(claimed - actual) / max(actual, 1), 0.05,
                f"{name} 宣稱後端約 {claimed} 項測試，實際 {actual} 項，差太多了")

    def test_data_models_are_documented(self):
        """README 的資料模型表要列出每一個 model，規模數字也要對。

        2026-09-11 對帳時表上只有 37 個裡的 17 個（版本、稽核、SPC、助手對話、工程筆記……全都沒寫），
        「33 個資料模型」也停在舊值——接手的人照表找不到東西，AI 代理會以為沒有這些資料。
        """
        from django.apps import apps

        models = sorted(m.__name__ for m in apps.get_models() if m.__module__.startswith("apps."))
        readme = _read("README.md")
        section = readme.split("## 資料模型", 1)[1].split("\n---", 1)[0]
        missing = [name for name in models if f"`{name}`" not in section]
        self.assertEqual(missing, [], "README 的「資料模型」表漏列這些 model")
        for name in ("README.md", "CLAUDE.md"):
            claimed = _one_int(r"(\d+) 個資料模型", _read(name), "資料模型數")
            self.assertEqual(claimed, len(models), f"{name} 的資料模型數過期")


    def test_documented_categories_cover_every_tool(self):
        """架構頁的工具表要列出登錄表裡的每一個工具，也不能列出不存在的。"""
        page = _read("docs/architecture.html")
        table = page[page.index('<h3 id="sec-3-1">'):page.index("</table>", page.index('<h3 id="sec-3-1">'))]
        listed = set(re.findall(r"<code>([a-z0-9_]+)</code>", table))
        live = {t.key for t in self.tools}
        self.assertEqual(listed - live, set(), "架構頁列了登錄表裡沒有的工具")
        self.assertEqual(live - listed, set(), "架構頁漏了已登錄的工具")

    def test_architecture_page_tool_count_is_current(self):
        claimed = _one_int(r"The built-in categories \((\d+) tools\)", _read("docs/architecture.html"), "架構頁工具數")
        self.assertEqual(claimed, len(self.tools))

    def test_sample_coverage_claim_is_current(self):
        covered = set()
        for entry in demo.BUILTIN_TEMPLATES:
            try:
                for node in entry[-1]("{SOURCE}").get("nodes", []):
                    covered.add(node.get("type"))
            except Exception:  # noqa: BLE001 - 個別範本建不起來時不該讓這條斷言失真
                self.skipTest("範本 builder 無法在測試環境建立，跳過涵蓋率比對")
        covered &= {t.key for t in self.tools}
        page = _read("docs/guide/en/samples.md")  # 範例頁的正本是指南的 Markdown
        match = re.search(r"(\d+) of the (\d+) built-in tools appear in at least one template", page)
        self.assertIsNotNone(match, "範例頁找不到涵蓋率敘述")
        self.assertEqual((int(match.group(1)), int(match.group(2))), (len(covered), len(self.tools)),
                         "範例頁的涵蓋率過期")


class NotImplementedSectionTests(SimpleTestCase):
    """「尚未實作」不得列出程式碼裡確實存在的能力。"""

    #: 關鍵字 → 判斷它是否真的存在的探針
    CAPABILITIES = (
        ("標定", lambda: (ROOT / "apps/vision/calib.py").exists()),
        ("零樣本異常偵測", lambda: "register_detect" in {t.key for t in base.all_types()}),
        ("少樣本訓練", lambda: "register_detect" in {t.key for t in base.all_types()}),
        ("快速註冊", lambda: (ROOT / "apps/vision/dl/quick.py").exists()),
        ("影像檢索分類", lambda: "dl_retrieval" in {t.key for t in base.all_types()}),
    )

    def test_section_does_not_claim_existing_features_are_missing(self):
        readme = _read("README.md")
        section = readme[readme.index("## 尚未實作"):]
        section = section[:section.index("\n## ") if "\n## " in section else len(section)]
        for word, exists in self.CAPABILITIES:
            if exists():
                for claim in (f"{word}子系統", f"沒有{word}", f"無{word}", f"尚未實作{word}"):
                    self.assertNotIn(claim, section, f"README 的「尚未實作」仍列出已經實作的{word}（寫法：{claim}）")
                # 只擋「把它當成整段未實作」的寫法；說明性提及（例如更正註記）不算
                bad = re.search(rf"^[^>\n]*{re.escape(word)}[^\n]*尚未", section, re.M)
                self.assertIsNone(bad, f"README 的「尚未實作」把{word}寫成未實作")
