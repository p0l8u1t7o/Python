#!/usr/bin/env python
"""產生合成資料集並寫入資料庫。

    python scripts/seed_demo.py --batches 20
    python scripts/seed_demo.py --batches 40 --noise 0.20 --no-anomalies

所有由此產生的批次，備註欄都會標示為「合成資料（demo 用，非實測）」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description="產生 ExpAnalysis 合成資料集")
    ap.add_argument("--batches", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20250114)
    ap.add_argument("--noise", type=float, default=0.12,
                    help="量測相對誤差（對數標準差）")
    ap.add_argument("--points", type=int, default=8, help="每批取樣點數")
    ap.add_argument("--no-anomalies", action="store_true",
                    help="不注入異常批次")
    ap.add_argument("--keep", action="store_true", help="保留既有資料")
    ap.add_argument("--dump-truth", type=Path,
                    help="把真值寫成 JSON，供離線驗證用")
    args = ap.parse_args()

    from expanalysis.config import SETTINGS
    from expanalysis.data.synthetic import SyntheticConfig, seed_database
    from expanalysis.logging_setup import setup_logging
    from expanalysis.service import get_service

    setup_logging(SETTINGS.log_level, SETTINGS.log_dir)
    svc = get_service()
    cfg = SyntheticConfig(n_batches=args.batches, seed=args.seed,
                          rel_noise=args.noise, n_sample_points=args.points,
                          inject_anomalies=not args.no_anomalies)
    truth = seed_database(svc.repo, cfg, clear=not args.keep)
    svc.invalidate()

    print(f"已產生 {args.batches} 批合成資料 → {SETTINGS.db_path}")
    if truth["injected_anomalies"]:
        print("注入的異常批次：")
        for bid, kind in truth["injected_anomalies"].items():
            print(f"  {bid}: {kind}")
    print("\n各元素的真實參數（供反解驗證比對）：")
    for el, v in truth["element_truth"].items():
        print(f"  {el}: k0={v['k0']}  delta/D={v['delta_over_d']}  "
              f"C0={v['c0']} ppm  LOD={v['lod']} ppm")

    if args.dump_truth:
        args.dump_truth.write_text(
            json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n真值已寫入 {args.dump_truth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
