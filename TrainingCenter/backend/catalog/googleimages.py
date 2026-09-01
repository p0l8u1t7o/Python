"""Google 圖片搜尋（Programmable Search Engine / Custom Search JSON API）與下載工具。

為什麼不直接爬 images.google.com：
  * 那個頁面的結果是 JS 動態產生的，HTML 裡拿不到原圖網址，得靠會隨時失效的內嵌 JSON。
  * 自動化抓取 google.com/search 違反 Google 服務條款，而且很快會被擋（429 / CAPTCHA）。
官方的 Custom Search JSON API 查的是同一個索引，直接回傳原圖網址與來源頁，免費層每天 100 次查詢。

設定（放專案根目錄 .env）：
  GOOGLE_CSE_API_KEY=...   # Google Cloud 的 API key，需在該專案啟用 "Custom Search API"
  GOOGLE_CSE_ID=...        # Programmable Search Engine 的搜尋引擎 ID（cx）
建立搜尋引擎時要開「搜尋整個網路」與「圖片搜尋」，見 https://programmablesearchengine.google.com/
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

ENDPOINT = "https://www.googleapis.com/customsearch/v1"
# 有些圖床會擋掉不像瀏覽器的 UA
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_BYTES = 8 * 1024 * 1024
MIN_PIXELS = 200  # 短邊至少要有這麼多像素，太小的縮圖不要
EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class ConfigError(RuntimeError):
    """金鑰或搜尋引擎 ID 沒設好。"""


class QuotaError(RuntimeError):
    """API 配額用完（免費層每天 100 次查詢）。"""


@dataclass
class Hit:
    """一筆圖片搜尋結果。"""

    title: str
    image_url: str
    page_url: str
    site: str
    mime: str
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.width}x{self.height} {self.site} — {self.title[:50]}"


def credentials() -> tuple[str, str]:
    key = os.environ.get("GOOGLE_CSE_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    cx = os.environ.get("GOOGLE_CSE_ID") or ""
    if not key or not cx:
        missing = [n for n, v in (("GOOGLE_CSE_API_KEY", key), ("GOOGLE_CSE_ID", cx)) if not v]
        raise ConfigError(
            f"缺少 {'、'.join(missing)}。請在專案根目錄的 .env 設定後重跑；"
            "設定方式見 catalog/googleimages.py 的說明或 README「Google 圖片」。"
        )
    return key, cx


def search(query: str, count: int = 5, rights: str = "", timeout: int = 20) -> list[Hit]:
    """查圖片。rights 可填 Google 的授權篩選字串（如 cc_publicdomain|cc_attribute）。"""
    key, cx = credentials()
    params = {
        "key": key,
        "cx": cx,
        "q": query,
        "searchType": "image",
        "num": max(1, min(count, 10)),  # API 單次最多 10 筆
        "imgType": "photo",
        "safe": "active",
    }
    if rights:
        params["rights"] = rights
    req = Request(f"{ENDPOINT}?{urlencode(params)}", headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        if e.code == 429 or "quotaExceeded" in body or "rateLimitExceeded" in body:
            raise QuotaError(f"Custom Search 配額已用完（{e.code}）。免費層每天 100 次查詢。") from e
        if e.code in (400, 403):
            raise ConfigError(f"Custom Search 回 {e.code}：{body}") from e
        raise

    hits = []
    for item in data.get("items", []):
        img = item.get("image", {})
        hits.append(
            Hit(
                title=item.get("title", ""),
                image_url=item.get("link", ""),
                page_url=img.get("contextLink", ""),
                site=item.get("displayLink", ""),
                mime=item.get("mime", ""),
                width=int(img.get("width") or 0),
                height=int(img.get("height") or 0),
            )
        )
    return hits


def download(hit: Hit, timeout: int = 25) -> tuple[bytes, str]:
    """抓圖並確認真的是張看得懂的點陣圖。回傳 (bytes, 副檔名)。

    只做驗證不做轉檔：原圖是什麼格式就存什麼，副檔名依實際解碼結果決定。
    """
    req = Request(hit.image_url, headers={"User-Agent": UA, "Referer": hit.page_url or ""})
    with urlopen(req, timeout=timeout) as r:
        length = int(r.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            raise ValueError(f"檔案過大（{length / 1e6:.1f} MB）")
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("檔案過大")

    with Image.open(io.BytesIO(raw)) as im:
        fmt, size = im.format, im.size
        im.verify()  # 抓半截或假圖
    if fmt not in EXT:
        raise ValueError(f"不支援的圖片格式 {fmt}")
    if min(size) < MIN_PIXELS:
        raise ValueError(f"解析度太低 {size[0]}x{size[1]}")
    return raw, EXT[fmt]


def best(query: str, count: int = 5, rights: str = "", delay: float = 0.4) -> tuple[Hit, bytes, str]:
    """查詢後依序嘗試下載，回傳第一張成功的。全部失敗則丟出最後一個錯誤。"""
    hits = search(query, count=count, rights=rights)
    if not hits:
        raise LookupError(f"查無結果：{query}")
    last: Exception | None = None
    for hit in hits:
        try:
            raw, ext = download(hit)
            return hit, raw, ext
        except (HTTPError, URLError, ValueError, OSError) as e:
            last = e
            time.sleep(delay)
    raise LookupError(f"{len(hits)} 個結果都下載失敗，最後錯誤：{last}")
