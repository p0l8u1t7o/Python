"""整合頁的「連線偵錯」：開關、時間線、與一句診斷。

診斷（:func:`diagnose`）不是猜；它照設備通訊協定文件的步驟順序，看時間線
裡最後停在哪一步，說出「下一步該檢查什麼」。沒有任何封包 → 連線層；有
CONNECT 但沒 PUBLISH → 節點沒發 NBIRTH；有 PUBLISH 但 ingest 拒收 → 解碼
或 topic；worker 說序號不對 → 重生。每一句都附上文件章節。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.db.models import Q
from django.utils.timezone import now
from ninja import Router, Schema

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.schemas import OkResponse
from apps.devices.models import EdgeNode, EdgeNodeCredential, IngressDebug, IngressTrace
from services import diagnostics as diag

router = Router(tags=["integration"])

MAX_MINUTES = 240


class DebugStatusOut(Schema):
    enabled: bool
    enabled_until: dt.datetime | None = None
    node_filter: str = ""
    capture_payload: bool = False
    trace_count: int = 0


class DebugEnableIn(Schema):
    minutes: int = 30
    node_filter: str = ""
    capture_payload: bool = True


class TraceOut(Schema):
    id: int
    ts: dt.datetime
    stage: str
    outcome: str
    group_id: str = ""
    edge_node_id: str = ""
    device_id: str = ""
    topic: str = ""
    kind: str = ""
    reason: str = ""
    message: str = ""
    detail: dict[str, Any] = {}
    size: int = 0


class DiagnosisOut(Schema):
    node_id: str
    registered: bool
    node_enabled: bool = False
    group_id_expected: str
    status: str = ""
    last_seen_at: dt.datetime | None = None
    rebirth_requested_at: dt.datetime | None = None
    credential_active: bool = False
    last_auth_at: dt.datetime | None = None
    counts: dict[str, int] = {}
    last_by_kind: dict[str, dt.datetime] = {}
    findings: list[dict[str, str]] = []
    verdict: str = ""
    verdict_level: str = "info"


def _row(ctx: AuthContext) -> IngressDebug | None:
    return IngressDebug.objects.filter(organization=ctx.organization).first()


def _status(ctx: AuthContext) -> dict:
    row = _row(ctx)
    active = bool(row and row.enabled_until and row.enabled_until > now())
    return {
        "enabled": active,
        "enabled_until": row.enabled_until if active else None,
        "node_filter": row.node_filter if row else "",
        "capture_payload": row.capture_payload if row else False,
        "trace_count": _visible(ctx).count(),
    }


def _visible(ctx: AuthContext):
    """這個租戶看得到的：自己的，加上未歸屬但明顯是自己的——group 等於租戶代碼、
    node id 是自己登記的閘道器（例如 topic 用錯 group 的那種封包）、或 broker 層事件。"""
    my_nodes = EdgeNode.objects.filter(organization=ctx.organization, deleted_at__isnull=True).values("node_id")
    return IngressTrace.objects.filter(
        Q(organization=ctx.organization)
        | Q(organization__isnull=True, group_id=ctx.organization.slug)
        | Q(organization__isnull=True, edge_node_id__in=my_nodes)
        | Q(organization__isnull=True, stage=diag.STAGE_BROKER)
    )


@router.get("/debug", response=DebugStatusOut)
def debug_status(request):
    return _status(request.auth)


@router.put("/debug", response=DebugStatusOut, auth=role_required(Role.ADMIN))
def debug_enable(request, payload: DebugEnableIn):
    ctx: AuthContext = request.auth
    minutes = max(1, min(int(payload.minutes), MAX_MINUTES))
    row, _ = IngressDebug.objects.update_or_create(
        organization=ctx.organization,
        defaults={
            "enabled_until": now() + dt.timedelta(minutes=minutes),
            "node_filter": payload.node_filter.strip(),
            "capture_payload": payload.capture_payload,
            "enabled_by": ctx.user,
        },
    )
    diag.invalidate()
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=row,
           payload={"action": "ingress_debug_enabled", "minutes": minutes, "node": row.node_filter})
    return _status(ctx)


@router.delete("/debug", response=DebugStatusOut, auth=role_required(Role.ADMIN))
def debug_disable(request):
    ctx: AuthContext = request.auth
    IngressDebug.objects.filter(organization=ctx.organization).update(enabled_until=None)
    diag.invalidate()
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=ctx.organization,
           payload={"action": "ingress_debug_disabled"})
    return _status(ctx)


@router.get("/debug/traces", response=list[TraceOut])
def debug_traces(request, node: str = "", after_id: int = 0, limit: int = 200, outcome: str = ""):
    ctx: AuthContext = request.auth
    qs = _visible(ctx)
    if node:
        qs = qs.filter(Q(edge_node_id=node) | Q(edge_node_id="", stage=diag.STAGE_BROKER))
    if after_id:
        qs = qs.filter(id__gt=after_id).order_by("id")
    else:
        qs = qs.order_by("-id")
    if outcome:
        qs = qs.filter(outcome=outcome)
    rows = list(qs[: max(1, min(limit, 1000))])
    if not after_id:
        rows.reverse()
    return rows


@router.delete("/debug/traces", response=OkResponse, auth=role_required(Role.ADMIN))
def debug_clear(request):
    ctx: AuthContext = request.auth
    _visible(ctx).delete()
    return {"ok": True, "message": "traces_cleared"}


@router.get("/debug/diagnose/{node_id}", response=DiagnosisOut)
def debug_diagnose(request, node_id: str):
    ctx: AuthContext = request.auth
    return diagnose(ctx, node_id)


# ---------------------------------------------------------------------------
# 診斷：照文件步驟找出「停在哪一步」
# ---------------------------------------------------------------------------
def diagnose(ctx: AuthContext, node_id: str) -> dict:
    org = ctx.organization
    node = EdgeNode.objects.filter(organization=org, node_id=node_id, deleted_at__isnull=True).first()
    credential = EdgeNodeCredential.objects.filter(edge_node=node).first() if node else None
    since = now() - dt.timedelta(hours=6)
    traces = list(
        _visible(ctx).filter(ts__gte=since).filter(Q(edge_node_id=node_id) | Q(edge_node_id="")).order_by("id")
    )
    counts: dict[str, int] = {}
    last_by_kind: dict[str, dt.datetime] = {}
    for t in traces:
        key = f"{t.stage}:{t.outcome}"
        counts[key] = counts.get(key, 0) + 1
        if t.kind:
            last_by_kind[t.kind] = t.ts

    findings: list[dict[str, str]] = []

    def add(level: str, text: str, ref: str = "") -> None:
        findings.append({"level": level, "text": text, "ref": ref})

    # 步驟 1：註冊與 group
    if node is None:
        add("error", f"平台沒有註冊名為 {node_id} 的閘道器（或已刪除）。請先在整合頁新增閘道器。", "device-protocol.html#1-步驟-1-拿到位址與憑證")
    else:
        if not node.is_enabled:
            add("error", "這個閘道器在平台上被停用；broker 認證與 ingest 都會拒絕。", "device-protocol.html#附錄-d-帳密與-acl")
        if node.group_id != org.slug:
            add("warning", f"節點登記的 group_id 是 {node.group_id}，但租戶代碼是 {org.slug}；topic 要用登記的那一個。", "device-protocol.html#1-1-三層位址")
    wrong_group = [t for t in traces if t.group_id and node is not None and t.group_id != node.group_id]
    if wrong_group:
        seen = sorted({t.group_id for t in wrong_group})
        add("error", f"收到的 topic 用了別的 group_id：{', '.join(seen)}；應為 {node.group_id if node else org.slug}。", "device-protocol.html#1-1-三層位址")

    # 步驟 2：連線層
    broker_ok = [t for t in traces if t.stage == diag.STAGE_BROKER and t.reason in ("connected", "connect", "auth_allow")]
    broker_bad = [t for t in traces if t.stage == diag.STAGE_BROKER and t.outcome in (diag.OUTCOME_REJECTED, diag.OUTCOME_WARNING)]
    ingest_any = [t for t in traces if t.stage == diag.STAGE_INGEST]
    if not traces:
        add("error", "偵錯開啟以來沒有任何來自這個節點的封包。依序檢查：broker 位址／port、帳號密碼、client id（建議 zqs:<node id>）、遺言 topic 是否含這個 node id。若用 EMQX，看 broker 端的認證記錄。", "device-protocol.html#2-步驟-2-建立-mqtt-連線")
    for t in broker_bad[-3:]:
        add("warning" if t.outcome == diag.OUTCOME_WARNING else "error", t.message, "device-protocol.html#2-步驟-2-建立-mqtt-連線")
    if credential is not None and not credential.is_active:
        add("error", "MQTT 憑證已被輪替或停用；請在整合頁重新產生一組。", "device-protocol.html#附錄-d-帳密與-acl")

    # 步驟 4/5：出生
    if traces and not ingest_any:
        if broker_ok:
            add("error", "broker 收到連線，但 ingestor 沒收到任何 Sparkplug 封包：節點連上後必須發 NBIRTH（topic spBv1.0/{group}/NBIRTH/{node}）。也確認 ingestor 行程有在跑（run_pipeline / run_ingestor）。", "device-protocol.html#4-步驟-4-nbirth")
    # 只看「最後一次成功 NBIRTH 之後」的拒收：之前的已經被設備自己修好了，
    # 留著只會讓一台已上線的閘道器看起來還在出錯。
    last_birth_ok = max((t.ts for t in ingest_any if t.kind == "NBIRTH" and t.outcome == diag.OUTCOME_OK), default=None)
    rejected = [
        t for t in ingest_any
        if t.outcome in (diag.OUTCOME_REJECTED, diag.OUTCOME_DROPPED) and (last_birth_ok is None or t.ts > last_birth_ok)
    ]
    earlier_rejects = sum(1 for t in ingest_any if t.outcome in (diag.OUTCOME_REJECTED, diag.OUTCOME_DROPPED)) - len(rejected)
    if earlier_rejects:
        add("info", f"NBIRTH 成功之前有 {earlier_rejects} 則封包被拒收，已被後續的正確封包取代；時間線裡仍看得到原因。", "")
    for t in rejected[-3:]:
        add("error", f"{t.kind or '封包'} 被 ingest 拒收：{t.reason} — {t.message}", "device-protocol.html#3-步驟-3-會組-payload")
    if ingest_any and "NBIRTH" not in last_by_kind and any(t.kind in ("DBIRTH", "DDATA") for t in ingest_any):
        add("error", "收到 DBIRTH／DDATA 但沒有 NBIRTH：NBIRTH 必須是連線後第一則（seq=0），否則節點維持「等待重生」。", "device-protocol.html#4-步驟-4-nbirth")

    # 步驟 3/9：序號與重生
    seq_issues = [t for t in traces if t.stage == diag.STAGE_WORKER and t.reason.startswith("seq")]
    for t in seq_issues[-2:]:
        add("warning", t.message, "device-protocol.html#3-3-seq-每一則-1")
    rebirths = [t for t in traces if t.reason == "rebirth_requested"]
    if rebirths:
        answered = any(t.kind == "NBIRTH" and t.ts > rebirths[-1].ts for t in ingest_any)
        if not answered:
            add("error", "平台已發 NCMD Node Control/Rebirth=true，但之後沒有收到新的 NBIRTH：設備沒有實作重生，會一直停在「等待重生」。", "device-protocol.html#9-步驟-9-重生")

    # 沒有設備
    if node is not None and not node.devices.filter(deleted_at__isnull=True).exists():
        add("info", "這個閘道器底下還沒有設備：NBIRTH 成功後節點會上線，但要有 DBIRTH 才會有量測值；先註冊設備再送 DBIRTH。", "device-protocol.html#5-步驟-5-dbirth")

    # 結論
    verdict, level = "", "info"
    if node is None:
        verdict, level = "節點未註冊", "error"
    elif node.status == "online" and not rejected:
        verdict, level = "節點已上線", "ok"
    elif not traces:
        verdict, level = "沒有收到任何封包：卡在連線層", "error"
    elif rejected:
        verdict, level = "封包有進來但被拒收：看拒收原因", "error"
    elif not ingest_any:
        verdict, level = "連上 broker 了，但沒有發 NBIRTH", "error"
    elif rebirths:
        verdict, level = "平台要求重生，設備沒有回應", "error"
    elif "NBIRTH" in last_by_kind:
        verdict, level = "NBIRTH 已收到；若仍顯示離線，看 worker 的序號警告", "warning"
    else:
        verdict, level = "有封包但沒有 NBIRTH", "error"

    return {
        "node_id": node_id,
        "registered": node is not None,
        "node_enabled": bool(node and node.is_enabled),
        "group_id_expected": node.group_id if node else org.slug,
        "status": node.status if node else "",
        "last_seen_at": node.last_seen_at if node else None,
        "rebirth_requested_at": node.rebirth_requested_at if node else None,
        "credential_active": bool(credential and credential.is_active),
        "last_auth_at": credential.last_auth_at if credential else None,
        "counts": counts,
        "last_by_kind": last_by_kind,
        "findings": findings,
        "verdict": verdict,
        "verdict_level": level,
    }


__all__ = ["router", "diagnose", "uuid"]
