#!/usr/bin/env python
"""在命令列跑完整驗證並印出驗收表。

    python scripts/run_validation.py

輸出的表格就是可以貼進報告的驗收文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _fmt(v, nd=4):
    return "—" if v is None or v != v else f"{v:.{nd}f}"


def main() -> int:
    from expanalysis.config import SETTINGS
    from expanalysis.logging_setup import setup_logging
    from expanalysis.ml.validation import censoring_comparison
    from expanalysis.service import get_service

    setup_logging("WARNING", SETTINGS.log_dir)
    svc = get_service()
    if svc.repo.count() == 0:
        print("資料庫沒有批次資料。請先執行 scripts/seed_demo.py 或匯入 CSV。")
        return 1

    print("=" * 68)
    print("留一批交叉驗證（Leave-One-Batch-Out）")
    print("=" * 68)
    res = svc.lobo()
    if not res.get("n_points"):
        print(res.get("verdict", "無法執行"))
        return 1

    print(f"折數 {res['n_batches']}　未設限測點 {res['n_points']}\n")
    print(f"{'指標':<22}{'純物理':>14}{'物理 + AI':>16}")
    print("-" * 68)
    for label, a, b in [
        ("平均絕對誤差 (ppm)", res["physics_mae_ppm"], res.get("ai_mae_ppm")),
        ("最大誤差 (ppm)", res["physics_max_ppm"], res.get("ai_max_ppm")),
        ("對數空間平均誤差", res["physics_mae_log"], res.get("ai_mae_log")),
    ]:
        print(f"{label:<22}{_fmt(a):>14}{_fmt(b):>16}")
    print("-" * 68)
    print(f"\n驗收判定：{res['verdict']}\n")

    print("分元素：")
    for el, v in (res.get("per_element") or {}).items():
        print(f"  {el:<4} 純物理 {_fmt(v['physics_mae_ppm'])} ppm　"
              f"物理+AI {_fmt(v.get('ai_mae_ppm'))} ppm　({v['n_points']} 點)")

    print("\n" + "=" * 68)
    print("設限資料處理方式對照")
    print("=" * 68)
    cs = censoring_comparison(svc.repo.all_details())
    els = list((cs.get("tobit") or {}).get("elements", {}))
    print(f"{'元素':<6}{'Tobit（正確）':>16}{'當成 0':>14}{'當成 LOD':>14}")
    print("-" * 68)
    for el in els:
        t = cs["tobit"]["elements"][el]["k_median"]
        z = cs["as_zero"]["elements"][el]["k_median"]
        l = cs["as_lod"]["elements"][el]["k_median"]
        print(f"{el:<6}{_fmt(t):>16}{_fmt(z):>14}{_fmt(l):>14}")
    print("-" * 68)
    print(cs.get("_note", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
