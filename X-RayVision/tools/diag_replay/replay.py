"""
原廠端工具 (不隨產品發布)：問題回報包重現

  python tools/diag_replay/replay.py <回報包路徑 (.xrvdiag / .xrvdiag.enc / .001)> [--key 私鑰.pem] [--out 資料夾]

步驟：
  1. 合併分割檔、解密、驗證每個檔案的雜湊值。
  2. 以回報包內的配方，用目前的引擎重新分析每張影像。
  3. 比對客戶端結果與重新分析結果 (判定、品質等級、影像層級向量結果)，輸出 replay.md。
  4. 版本不同時 (客戶端與目前引擎)，差異可能來自改版；報告會標示版本。
"""
import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from xrayvision import __version__  # noqa: E402
from xrayvision.core import plugin, serialize  # noqa: E402
from xrayvision.core.pipeline import Recipe, analyze_image  # noqa: E402
from xrayvision.service.diagnostics import read_package  # noqa: E402


def _vec(res, module_id):
    cls = plugin.get(module_id)
    m = next((m for m in res["modules"] if m["module_id"] == module_id), None)
    if not m or not cls.summary_vector:
        return None
    return (m["summary"] or {}).get(cls.summary_vector)


def replay(package, key_path=None, out_dir="replay"):
    key = open(key_path, "rb").read() if key_path else None
    z, manifest = read_package(package, key)
    runs = json.loads(z.read("runs.json"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="xrv_replay_")
    rows = []
    for r in runs:
        orig = json.loads(z.read(r["result_entry"]))
        rc = json.loads(z.read(f"recipes/recipe{r['recipe_pk']}.json"))
        body = rc["body"]
        body["modules"] = [{k: v for k, v in m.items() if k != "module_version"} for m in body["modules"]]
        if not r["image_entry"]:
            rows.append(dict(run=r["run_id"], image=r["image_file"], status="no_image"))
            continue
        img_path = os.path.join(tmp, os.path.basename(r["image_entry"]))
        with open(img_path, "wb") as f:
            f.write(z.read(r["image_entry"]))
        new, _ = analyze_image(img_path, Recipe.from_dict(body), acquisition_record=orig.get("acquisition"))
        new = serialize.to_jsonable(new)
        serialize.dump(new, os.path.join(out_dir, f"run{r['run_id']}.replay.json"))
        diffs = []
        if orig["judgment"] != new["judgment"]:
            diffs.append(f"judgment {orig['judgment']} -> {new['judgment']}")
        if orig["quality"]["level"] != new["quality"]["level"]:
            diffs.append(f"quality {orig['quality']['level']} -> {new['quality']['level']}")
        for m in orig["modules"]:
            a, b = _vec(orig, m["module_id"]), _vec(new, m["module_id"])
            if a and b and (abs(a["dx"] - b["dx"]) > 0.005 or abs(a["dy"] - b["dy"]) > 0.005):
                diffs.append(f"{m['module_id']} ({a['dx']:+.3f},{a['dy']:+.3f}) -> ({b['dx']:+.3f},{b['dy']:+.3f})")
        rows.append(dict(run=r["run_id"], image=r["image_file"], final=r["final_judgment"],
                         reviews=len(r["reviews"]), diffs=diffs, status="same" if not diffs else "different"))
    L = ["# Diagnostic Package Replay", "",
         f"- Package: {os.path.basename(package)}",
         f"- Customer software version: {manifest['software_version']}; modules {manifest['modules']}",
         f"- Replay software version: {__version__}; modules { {k: v.version for k, v in plugin.available().items()} }",
         f"- Options: {manifest['options']}", "", "## Description", "",
         z.read("description.txt").decode("utf-8") or "-", "", "## Runs", "",
         "| Run | Image | Final judgment | Reviews | Replay | Differences |", "|---|---|---|---|---|---|"]
    for x in rows:
        L.append(f"| {x['run']} | {x['image']} | {x.get('final', '')} | {x.get('reviews', '')} | {x['status']} | "
                 f"{'; '.join(x.get('diffs', [])) or '-'} |")
    with open(os.path.join(out_dir, "replay.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--key", default=None, help="private key (PEM) for encrypted packages")
    ap.add_argument("--out", default="replay")
    a = ap.parse_args()
    rows = replay(a.package, a.key, a.out)
    same = sum(r["status"] == "same" for r in rows)
    print(f"{len(rows)} runs replayed, {same} identical; report: {os.path.join(a.out, 'replay.md')}")


if __name__ == "__main__":
    main()
