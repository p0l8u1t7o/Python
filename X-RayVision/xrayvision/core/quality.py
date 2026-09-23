"""
成像品質指標與閘門 (成像條件對策第四層)

指標分兩類：
  - 平台指標 (image.*)：與檢測項目無關，例如訊雜比、飽和比例。
  - 模組指標 (<module_id>.*)：檢測模組回報的品質指標，例如凸塊對比、邊緣模糊寬度。
規則以「指標 + 警告／不合格門檻」表示；平台與模組各有預設規則，配方可依指標鍵覆寫。
閘門結果分三級：pass (合格)、warn (警告，照常分析並註記)、fail (不合格，不輸出判定)。
"""
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .io import KIND_RAW16

PASS, WARN, FAIL = "pass", "warn", "fail"
_ORDER = {PASS: 0, WARN: 1, FAIL: 2}


@dataclass
class QualityRule:
    metric: str
    warn_below: float = None
    warn_above: float = None
    fail_below: float = None
    fail_above: float = None
    kinds: tuple = (KIND_RAW16,)       # 適用的影像類型

    def evaluate(self, value):
        if value is None:
            return None
        if (self.fail_below is not None and value < self.fail_below) or \
                (self.fail_above is not None and value > self.fail_above):
            return FAIL
        if (self.warn_below is not None and value < self.warn_below) or \
                (self.warn_above is not None and value > self.warn_above):
            return WARN
        return PASS

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        if "kinds" in d:
            d["kinds"] = tuple(d["kinds"])
        return cls(**d)

    def to_dict(self):
        return asdict(self)


# 平台預設規則 (初始值；取得現場參數掃描影像後校正)
PLATFORM_RULES = (
    QualityRule("image.snr", warn_below=80.0, fail_below=30.0),
    QualityRule("image.saturation_ratio", warn_above=0.001, fail_above=0.01),
    QualityRule("image.dark_ratio", warn_above=0.001, fail_above=0.01),
)


def image_metrics(image):
    """
    平台指標：
      snr              背景訊雜比 = 中位強度 / 雜訊 (雜訊以高通影像的 MAD 估計)
      saturation_ratio 接近滿刻度的像素比例
      dark_ratio       接近零的像素比例
      dynamic_range    0.5%～99.5% 百分位跨度佔滿刻度的比例
    """
    g = image.pixels.astype(np.float32)
    full = 65535.0 if image.kind == KIND_RAW16 else 255.0
    hp = g - cv2.GaussianBlur(g, (0, 0), 2.0)
    noise = 1.4826 * float(np.median(np.abs(hp)))
    med = float(np.median(g))
    lo, hi = np.percentile(g, [0.5, 99.5])
    return {
        "image.snr": med / max(noise, 1e-6),
        "image.saturation_ratio": float((image.pixels >= full * 0.999).mean()),
        "image.dark_ratio": float((image.pixels <= full * 0.001).mean()),
        "image.dynamic_range": float((hi - lo) / full),
        "image.median_level": med / full,
    }


def merge_rules(*rule_sets):
    """後面的規則集依指標鍵覆寫前面的"""
    out = {}
    for rs in rule_sets:
        for r in rs:
            out[r.metric] = r
    return list(out.values())


def evaluate(metrics, rules, kind):
    """回傳 (level, checks)；checks 為每條適用規則的結果"""
    checks = []
    level = PASS
    for r in rules:
        if kind not in r.kinds or r.metric not in metrics:
            continue
        v = metrics[r.metric]
        lv = r.evaluate(v)
        if lv is None:
            continue
        checks.append(dict(metric=r.metric, value=v, level=lv, rule=r.to_dict()))
        if _ORDER[lv] > _ORDER[level]:
            level = lv
    return level, checks


def worst(*levels):
    return max(levels, key=lambda lv: _ORDER[lv])
