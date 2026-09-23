"""
自我檢查：以內建標準影像執行分析，結果須與預期一致 (進版後由啟動器呼叫 /api/health?selftest=1)。
可發現執行環境損毀、函式庫版本不符、程式檔不完整等問題。預期結果於建置發行版時以該版本重新產生。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE = os.path.join(HERE, "reference.tiff")
EXPECTED = os.path.join(HERE, "expected.json")
RECIPE = {"recipe_id": "selftest", "version": 1, "modules": [{"module_id": "bump_alignment"}]}
TOLERANCE_PX = 0.01


def _measure():
    from ..core.pipeline import Recipe, analyze_image
    res, _ = analyze_image(IMAGE, Recipe.from_dict(RECIPE))
    m = res.modules[0]
    d = m.summary.get("die_shift") or {}
    return dict(status=m.status, sites_used=m.summary.get("sites_used"), dx=round(d.get("dx", 0.0), 4),
                dy=round(d.get("dy", 0.0), 4))


def run():
    """回傳 ("pass" | "fail", 說明)"""
    try:
        exp = json.load(open(EXPECTED, encoding="utf-8"))
        got = _measure()
    except Exception as e:                                        # noqa: BLE001
        return "fail", repr(e)
    ok = (got["status"] == exp["status"] and got["sites_used"] == exp["sites_used"]
          and abs(got["dx"] - exp["dx"]) <= TOLERANCE_PX and abs(got["dy"] - exp["dy"]) <= TOLERANCE_PX)
    return ("pass" if ok else "fail"), json.dumps(dict(expected=exp, actual=got))


def generate_expected():
    """建置發行版時呼叫：以目前版本產生預期結果"""
    got = _measure()
    with open(EXPECTED, "w", encoding="utf-8") as f:
        json.dump(got, f, indent=1)
    return got
