"""跑 AI 助手評測基準：manage.py agent_bench [--llm] [--keys k1,k2] [--json out.json]

預設用離線規則引擎（不連外）；--llm 用目前伺服器 .env 的供應商設定（需金鑰），
用來比較不同供應商／模型在同一批案例上的表現。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.vision.agent import bench, providers


class Command(BaseCommand):
    help = "跑 AI 助手評測基準（意圖準確率／判定準確率／graph 有效率）"

    def add_arguments(self, parser):
        parser.add_argument("--llm", action="store_true", help="用伺服器設定的 LLM 供應商（預設離線規則引擎）")
        parser.add_argument("--keys", default="", help="只跑指定案例（逗號分隔 key）")
        parser.add_argument("--json", default="", help="把完整結果寫成 JSON 檔")

    def handle(self, *args, **options):
        keys = [k.strip() for k in options["keys"].split(",") if k.strip()] or None
        settings = providers.server_settings() if options["llm"] else None
        out = bench.run_bench(settings, use_llm=True if options["llm"] else False, keys=keys)
        self.stdout.write(f"{'案例':28} {'意圖':8} {'判定':22} {'有效':4} {'ms':>6}")
        for r in out["cases"]:
            intent = f"{'✓' if r['intent_ok'] else '✗'} {r.get('intent', '')}"
            statuses = "/".join(f"{s}{'' if m else '!'}" for s, m in zip(r.get("statuses", []), r.get("status_matches", []))) or (r.get("error") or "-")[:22]
            self.stdout.write(f"{r['key']:28} {intent:8} {statuses:22} {'✓' if r['valid'] else '✗':4} {r['ms']:6}")
        s = out["summary"]
        self.stdout.write(f"\n案例 {s['n']}：意圖 {s['intent_acc']:.0%}、判定（案例）{s['status_acc']:.0%}、判定（影像）{s['image_acc']:.0%}、有效 {s['valid_rate']:.0%}、共 {s['total_ms']} ms")
        if s["failed"]:
            self.stdout.write("未通過：" + ", ".join(s["failed"]))
        if options["json"]:
            with open(options["json"], "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=2)
            self.stdout.write(f"已寫入 {options['json']}")
