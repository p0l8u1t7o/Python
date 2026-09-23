"""
回歸影像集：以固定影像集的分析結果為基準，改版後比對差異。

更新基準 (演算法有意變更、並經審閱後才執行)：
    python -m tests.regression.regress --update
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from xrayvision.core import runtime  # noqa: E402
from xrayvision.core.io import list_images  # noqa: E402
from xrayvision.core.pipeline import Recipe, analyze_image  # noqa: E402

IMAGE_SETS = [os.path.join(ROOT, "image", "Batch1"), os.path.join(ROOT, "image", "Batch2")]
RECIPE = os.path.join(ROOT, "recipes", "bump_alignment_default.json")
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def _r(v, nd=4):
    return None if v is None else round(float(v), nd)


def _est(e):
    if not e:
        return None
    return dict(dx=_r(e["dx"]), dy=_r(e["dy"]), se=_r(e["se"]), n=e["n"], n_in=e["n_in"])


def summarize(path):
    runtime.apply_limits(low_priority=True, cv_threads=1)
    res, _ = analyze_image(path, Recipe.load(RECIPE))
    m = res.modules[0]
    key = os.path.relpath(path, ROOT).replace("\\", "/")
    return key, dict(kind=res.image["kind"], reference_only=res.reference_only, status=m.status,
                     sites_measured=m.summary.get("sites_measured"), sites_used=m.summary.get("sites_used"),
                     die_shift=_est(m.summary.get("die_shift")),
                     groups=[dict(id=g.id, size=g.size, est=_est(g.estimate)) for g in m.groups])


def available_images():
    return [f for d in IMAGE_SETS if os.path.isdir(d) for f in list_images([d])]


def run_all(files, workers=None):
    workers = workers or runtime.default_workers()
    with ProcessPoolExecutor(min(workers, len(files))) as ex:
        return dict(ex.map(summarize, files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    cur = run_all(available_images())
    if a.update:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"baseline updated: {len(cur)} images")
        return 0
    base = json.load(open(BASELINE, encoding="utf-8"))
    diffs = compare(base, cur)
    for d in diffs:
        print(d)
    print(f"{len(cur)} images, {len(diffs)} differences")
    return 1 if diffs else 0


def compare(base, cur, tol_px=0.005):
    diffs = []
    for k, b in base.items():
        c = cur.get(k)
        if c is None:
            diffs.append(f"{k}: missing")
            continue
        for f in ("kind", "reference_only", "status", "sites_measured", "sites_used"):
            if b[f] != c[f]:
                diffs.append(f"{k}: {f} {b[f]} -> {c[f]}")
        pairs = [("image", b["die_shift"], c["die_shift"])]
        if len(b["groups"]) != len(c["groups"]):
            diffs.append(f"{k}: groups {len(b['groups'])} -> {len(c['groups'])}")
        else:
            pairs += [(f"group {g['id']}", g["est"], h["est"]) for g, h in zip(b["groups"], c["groups"])]
        for name, e1, e2 in pairs:
            if (e1 is None) != (e2 is None):
                diffs.append(f"{k}: {name} estimate {e1} -> {e2}")
            elif e1 and (abs(e1["dx"] - e2["dx"]) > tol_px or abs(e1["dy"] - e2["dy"]) > tol_px
                         or e1["n_in"] != e2["n_in"]):
                diffs.append(f"{k}: {name} ({e1['dx']:+.4f},{e1['dy']:+.4f}) n_in {e1['n_in']} -> "
                             f"({e2['dx']:+.4f},{e2['dy']:+.4f}) n_in {e2['n_in']}")
    return diffs


if __name__ == "__main__":
    sys.exit(main())
