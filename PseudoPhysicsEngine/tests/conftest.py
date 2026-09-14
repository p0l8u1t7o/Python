"""Windows 原生函式庫載入順序保護。

同一程序裡若先建立 OCP XCAF 物件、之後才載入 PyMuPDF，Python 結束清理時會堆積毀損
（0xC0000374）。先載入 PyMuPDF 則正常，因此在收集任何測試模組、建立任何 OCP 物件之前就載入它。
詳見 docs/DECISIONS.md D-011。
"""

import pymupdf  # noqa: F401
