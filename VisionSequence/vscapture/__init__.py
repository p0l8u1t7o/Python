"""VisionSequence 擷取端（capture client）：安裝在相機所在電腦，直接驅動相機並把影像送到伺服端。

本檔零依賴：伺服端只 import `vscapture.protocol`（共用的線上協定），桌面程式本體在 `vscapture.app`。
"""

__version__ = "0.2.0"
