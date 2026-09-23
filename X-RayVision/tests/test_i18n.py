"""語系完整性：繁中與英文鍵一致；模組用到的代碼都有翻譯；產品文字不含設備廠牌"""
import json
import os
import re

from xrayvision.core import plugin
from xrayvision.i18n import LOCALES, catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 產品內不得出現的設備廠牌與型號字樣 (不分大小寫)
FORBIDDEN = re.compile(r"nordson|dage|quadra|revalution|onyx", re.I)


def test_locales_have_same_keys():
    keys = [set(catalog(loc)) for loc in LOCALES]
    assert all(k == keys[0] for k in keys), set.symmetric_difference(*keys)


def test_module_codes_translated():
    cat = catalog("en")
    for mid, cls in plugin.available().items():
        assert f"module.{mid}" in cat
        for r in cls.quality_rules:
            assert f"metric.{r.metric}" in cat, r.metric
    for code in ("border", "on_ball", "masked", "model_diverged", "low_contrast", "bump_coverage", "bump_fit",
                 "bump_rms", "pad_coverage", "pad_fit", "pad_rms", "pad_inside_bump", "isolated", "radius_outlier"):
        assert f"reject.{code}" in cat, code


ERROR_PATTERNS = [
    re.compile(r'(?:Api|Auth)Error\(\d+, "([a-z_]+)"'),
    re.compile(r'raise (?:ImportFailed|RecipeStoreError|WatchError|DiagnosticsError|CalibrationError|RecipeError|'
               r'ImageFormatError|LicenseError|UpdateError|ArchiveError|ModuleValidationError|ModelPackageError|ModelError|InferenceError|AnnotationError|ValidationSetError)\("([a-z_]+)"'),
    re.compile(r'ok=False, error="([a-z_]+)"'),
    re.compile(r'_finish_failed\(job_id, "([a-z_]+)"'),
]


def test_all_error_codes_translated():
    codes = set()
    for base, _, files in os.walk(os.path.join(ROOT, "xrayvision")):
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(base, f), encoding="utf-8").read()
                for pat in ERROR_PATTERNS:
                    codes |= set(pat.findall(src))
    assert len(codes) > 20
    for loc in LOCALES:
        missing = sorted(c for c in codes if f"error.{c}" not in catalog(loc))
        assert not missing, (loc, missing)
    for j in ("pass", "fail", "review", "quality_insufficient", "not_judged"):
        assert f"judgment.{j}" in catalog("en")


def test_frontend_keys_translated():
    """前端 t("…") 用到的固定鍵都要在語系檔中"""
    src = os.path.join(ROOT, "web", "src")
    if not os.path.isdir(src):
        return
    keys = set()
    pat = re.compile(r'\bt\("([a-z]+\.[a-zA-Z0-9_.]+)"')
    for base, _, files in os.walk(src):
        for f in files:
            if f.endswith((".ts", ".tsx")):
                keys |= set(pat.findall(open(os.path.join(base, f), encoding="utf-8").read()))
    assert len(keys) > 100
    for loc in LOCALES:
        missing = sorted(k for k in keys if k not in catalog(loc))
        assert not missing, (loc, missing)


def test_no_equipment_brand_in_product_text():
    hits = []
    for base, _, files in os.walk(os.path.join(ROOT, "xrayvision")):
        for f in files:
            if f.endswith((".py", ".json")):
                p = os.path.join(base, f)
                with open(p, encoding="utf-8") as fh:
                    for i, line in enumerate(fh, 1):
                        if FORBIDDEN.search(line):
                            hits.append(f"{os.path.relpath(p, ROOT)}:{i}")
    for loc in LOCALES:
        assert not FORBIDDEN.search(json.dumps(catalog(loc), ensure_ascii=False))
    assert not hits, hits
