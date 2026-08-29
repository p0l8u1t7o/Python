"""manage.py regress <flow_id|name> [--fail-under 1.0] [--json] [--save-baseline] [--graph file.flow.json]

match 率低於 --fail-under 時退出碼 1（可進 CI）；沒有任何 golden case 時退出碼 3。
"""

from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from apps.core.errors import APIError
from apps.golden import regress
from apps.vision import serialize


class Command(BaseCommand):
    help = "用 Golden Set 對流程做回歸測試"

    def add_arguments(self, parser):
        parser.add_argument("flow", help="流程 id 或名稱")
        parser.add_argument("--fail-under", type=float, default=1.0, dest="fail_under", help="match 率門檻（預設 1.0：任何 mismatch 都失敗）")
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--save-baseline", action="store_true", dest="save_baseline")
        parser.add_argument("--graph", default="", help="用 .flow.json 檔內的 graph 取代 DB 的圖（來源用 --source）")
        parser.add_argument("--source", type=int, default=None)

    def handle(self, *args, **opts):
        flow = serialize.find_flow(opts["flow"])
        if flow is None:
            raise CommandError(f"流程不存在：{opts['flow']}")
        graph = None
        if opts["graph"]:
            with open(opts["graph"], "rb") as f:
                doc = serialize.parse(f.read())
            graph = serialize.materialize_graph(doc, source_id=opts["source"])
        try:
            result = regress.run_regression(flow, graph=graph, save_baseline=opts["save_baseline"], fail_under=opts["fail_under"])
        except APIError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
        if opts["as_json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            self._print(result)
        if result["total"] == 0:
            sys.exit(3)
        if not result["passed"]:
            sys.exit(1)

    def _print(self, r):
        w = self.stdout.write
        w(f"流程 {r['flow_name']}（id={r['flow_id']}, v{r['flow_version']}）  基準 v{r['baseline_version']}" if r["baseline_version"] is not None else f"流程 {r['flow_name']}（id={r['flow_id']}, v{r['flow_version']}）  無基準")
        w(f"total={r['total']}  match={r['match']}  mismatch={r['mismatch']}  rate={r['match_rate']:.4f}  {r['duration_ms']:.0f} ms")
        c = r["confusion"]
        w(f"confusion tp={c['tp']} fp={c['fp']} tn={c['tn']} fn={c['fn']}")
        if r["regressed"]:
            w(self.style.ERROR(f"REGRESSED ({len(r['regressed'])}):"))
            for x in r["regressed"]:
                w(f"  #{x['case_id']} {x['name']}: {x['was']} -> {x['now']}  node={x['node'] or '-'}  {'; '.join(x['reasons'])} {x['error']}".rstrip())
        if r["improved"]:
            w(self.style.SUCCESS(f"IMPROVED ({len(r['improved'])}):"))
            for x in r["improved"]:
                w(f"  #{x['case_id']} {x['name']}: {x['was']} -> {x['now']}")
        others = [x for x in r["cases"] if not x["match"] and x["was_match"] is not False and not any(x["case_id"] == g["case_id"] for g in r["regressed"])]
        if others:
            w(f"MISMATCH ({len(others)}):")
            for x in others:
                w(f"  #{x['case_id']} {x['name']}: expect {x['expect']} got {x['status']}  {'; '.join(x['reasons'])}")
        if r["baseline_saved"]:
            w(f"已儲存基準 v{r['baseline_version']}")
        w(self.style.SUCCESS("PASS") if r["passed"] else self.style.ERROR(f"FAIL（rate {r['match_rate']:.4f} < {r['fail_under']}）"))
