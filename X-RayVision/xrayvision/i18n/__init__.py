"""語系：產品顯示文字一律由此取得"""
import json
import os
from functools import lru_cache

LOCALES = ("zh-TW", "en")
DEFAULT_LOCALE = "zh-TW"


@lru_cache(maxsize=None)
def base_catalog(locale):
    if locale not in LOCALES:
        locale = DEFAULT_LOCALE
    with open(os.path.join(os.path.dirname(__file__), f"{locale}.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def catalog(locale):
    """
    平台語系檔＋檢測模組以 translations 宣告的文字 (平台既有的鍵不會被覆蓋)。
    模組於啟動時載入後不再變動，結果快取；動態註冊模組後呼叫 catalog.cache_clear()
    """
    base = base_catalog(locale)
    try:
        from ..core import plugin
        extra = {}
        for cls in plugin.available().values():
            tr = getattr(cls, "translations", None) or {}
            for k, v in (tr.get(locale if locale in LOCALES else DEFAULT_LOCALE) or {}).items():
                if k not in base:
                    extra[k] = v
    except Exception:                                             # noqa: BLE001  模組載入失敗時仍提供平台文字
        extra = {}
    if not extra:
        return base
    return {**base, **extra}


def t(key, locale=DEFAULT_LOCALE):
    """取得文字；找不到時回傳鍵本身，方便發現漏翻"""
    return catalog(locale).get(key, key)
