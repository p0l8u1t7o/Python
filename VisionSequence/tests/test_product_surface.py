"""產品表面不得出現深度學習技術名稱（YOLO／ultralytics）：工具目錄、訓練方式目錄、內建範本、前端字典、docs 內文。

使用者只需要知道「AI 物件偵測」這種功能名稱；技術名稱只留在程式碼、模組名與 <code> 片段。
"""

from __future__ import annotations

import glob
import json
import os
import re

from django.conf import settings
from django.test import TestCase

BANNED = ("yolo", "ultralytics")
#: 介面字典再多擋模型名（docs 的安裝與疑難排解段落仍需要真實套件名，所以只用在字典上）
UI_BANNED = (r"\bSAM\d*\b",)
#: 技術來源字樣（CLAUDE.md 紅線）：工具目錄與介面字典都不准出現；docs 是技術文件，不掃。
TECH_BANNED = ("opencv", r"\bcv2\b", "ni vision")
#: 例外：使用者要在腳本裡 import 這些模組，help 列出模組名是功能需要（同 plugins.html 的 import 例外）。
TECH_EXEMPT_TOOLS = ("python_script",)


def _strip_exempt_tool_blocks(text: str) -> str:
    """把 tools.zh-*.ts 裡例外工具的整個區塊（`  key: {` … `  },`）拿掉再掃。"""
    import re as _re

    for key in TECH_EXEMPT_TOOLS:
        text = _re.sub(rf"^  {key}: \{{.*?^  \}},?$", "", text, flags=_re.S | _re.M)
    return text

ROOT = str(settings.BASE_DIR)


def _hits(text: str, words=BANNED) -> list[str]:
    """比對不分大小寫；但**全大寫的樣式**（UI_BANNED 的 SAM）刻意區分大小寫比對——
    不然 i18n 的鍵名 autoLabelSam／samRemaining 會被誤判成畫面上的技術名稱。"""
    low = text.lower()
    out = []
    for w in words:
        cased = w != w.lower()          # 樣式本身帶大寫＝要求原文也是大寫
        for m in re.finditer(w, text if cased else low):
            out.append(text[max(0, m.start() - 50):m.end() + 50].replace("\n", " "))
    return out


class ProductSurfaceTests(TestCase):
    def test_tool_catalogue(self):
        from apps.vision.tools import base as tools

        self.assertEqual(_hits(json.dumps(tools.catalogue(), ensure_ascii=False)), [])

    def test_tool_catalogue_has_no_technology_source_names(self):
        """OpenCV／cv2／NI Vision 不得出現在工具的 label／description／help（python_script 除外）。"""
        from apps.vision.tools import base, register_builtins

        register_builtins()
        for tool in base.all_types():
            if tool.key in TECH_EXEMPT_TOOLS:
                continue
            blob = json.dumps({"label": tool.label, "description": tool.description,
                               "params": [(p.key, p.label, getattr(p, "help_text", ""), getattr(p, "options", None)) for p in tool.params],
                               "ports": [(p.key, p.label) for p in list(tool.inputs) + list(tool.outputs)]}, ensure_ascii=False)
            with self.subTest(tool=tool.key):
                self.assertEqual(_hits(blob, TECH_BANNED), [])

    def test_trainer_catalogue(self):
        from apps.vision.dl import base

        self.assertEqual(_hits(json.dumps(base.catalogue(), ensure_ascii=False)), [])

    def test_builtin_templates(self):
        from apps.vision.api_more import SOURCE_PLACEHOLDER
        from apps.vision.demo import BUILTIN_TEMPLATES

        for key, name, desc, _cat, builder in BUILTIN_TEMPLATES:
            with self.subTest(key=key):
                self.assertEqual(_hits(key + " " + name + " " + desc), [])
                self.assertEqual(_hits(json.dumps(builder(SOURCE_PLACEHOLDER), ensure_ascii=False)), [])

    def test_frontend_locales(self):
        files = glob.glob(os.path.join(ROOT, "frontend", "src", "i18n", "locales", "*.ts"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(file=os.path.basename(f)):
                with open(f, encoding="utf-8") as fh:
                    # 介面字典是使用者每天看的字，連模型名（SAM／SAM2）都不該出現：
                    # 曾經有「SAM 全圖提案」這種按鈕名一路留到畫面上。
                    text = fh.read()
                    self.assertEqual(_hits(text, BANNED + UI_BANNED), [])
                    # 技術來源字樣：先把 python_script 那一塊拿掉（它列出可 import 的模組名是功能需要）
                    self.assertEqual(_hits(_strip_exempt_tool_blocks(text), TECH_BANNED), [])

    def test_docs_prose(self):
        files = glob.glob(os.path.join(ROOT, "docs", "*.html"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(file=os.path.basename(f)):
                with open(f, encoding="utf-8") as fh:
                    body = fh.read()
                body = re.sub(r"<code>.*?</code>|<pre[\s\S]*?</pre>|<!--[\s\S]*?-->", "", body)
                self.assertEqual(_hits(body, ("yolo",)), [])
