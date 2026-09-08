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
                    self.assertEqual(_hits(fh.read(), BANNED + UI_BANNED), [])

    def test_docs_prose(self):
        files = glob.glob(os.path.join(ROOT, "docs", "*.html"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(file=os.path.basename(f)):
                with open(f, encoding="utf-8") as fh:
                    body = fh.read()
                body = re.sub(r"<code>.*?</code>|<pre[\s\S]*?</pre>|<!--[\s\S]*?-->", "", body)
                self.assertEqual(_hits(body, ("yolo",)), [])
