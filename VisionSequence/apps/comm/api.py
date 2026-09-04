"""通訊連線 API（掛在 /vision 底下）。

GET    /vision/connections/kinds
GET    /vision/connections                  任何登入者可讀
POST   /vision/connections                  管理員
GET    /vision/connections/{id}
PATCH  /vision/connections/{id}             管理員；設定變更會重開連線
DELETE /vision/connections/{id}             管理員
POST   /vision/connections/{id}/test        管理員：重新連線並回 info（失敗回 ok=false 與錯誤）
POST   /vision/connections/{id}/write       管理員：手動寫一筆 {"values": {"coil:0": 1}}
GET    /vision/connections/{id}/state       讀回 ?addresses=a,b（dio_sim 不帶參數回全部狀態）

從站（`modbus_server`）與設了 `trigger_address` 的連線在建立／修改後會立刻開起來，
伺服器啟動時也會自動開（`writers.autostart()`，由 `manage.py serve` 呼叫）。
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router, Schema

from apps.accounts.security import principal, require_feature
from apps.comm import writers
from apps.comm.models import Connection
from apps.core import audit
from apps.core.errors import Conflict, ValidationError

router = Router(tags=["comm"])


class ConnectionIn(Schema):
    name: str
    kind: str
    config: dict[str, Any] = {}
    is_enabled: bool = True


class ConnectionPatch(Schema):
    name: str | None = None
    kind: str | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None


class WriteIn(Schema):
    values: dict[str, Any]
    timeout_s: float | None = None


def _out(conn: Connection) -> dict[str, Any]:
    return {
        "id": conn.id,
        "name": conn.name,
        "kind": conn.kind,
        "config": conn.config or {},
        "is_enabled": conn.is_enabled,
        "status": writers.connection_info(conn),
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }


def _check_kind(kind: str, config: dict[str, Any]) -> None:
    writers._resolve_class(kind, config)  # 未知 kind 直接 422


@router.get("/connections/kinds")
def list_kinds(request: HttpRequest):
    principal(request)
    return {"items": writers.kinds()}


@router.get("/connections")
def list_connections(request: HttpRequest):
    principal(request)
    return {"items": [_out(c) for c in Connection.objects.all()]}


@router.post("/connections", response={201: dict})
def create_connection(request: HttpRequest, payload: ConnectionIn):
    require_feature(request, "connections")
    name = payload.name.strip()
    if not name:
        raise ValidationError("A name is required", code="connection_name_required")
    _check_kind(payload.kind, payload.config)
    try:
        with transaction.atomic():
            conn = Connection.objects.create(name=name, kind=payload.kind, config=payload.config, is_enabled=payload.is_enabled)
    except IntegrityError:
        raise Conflict("A connection with that name already exists", code="connection_name_taken") from None
    writers.ensure_started(conn)  # 從站與觸發輪詢不必等到有人按「測試」
    audit.record(request, "connection.create", conn, summary=conn.kind, detail={"config": conn.config})
    return 201, _out(conn)


@router.get("/connections/{connection_id}")
def get_connection(request: HttpRequest, connection_id: int):
    principal(request)
    return _out(writers.get_connection(connection_id))


@router.patch("/connections/{connection_id}")
def patch_connection(request: HttpRequest, connection_id: int, payload: ConnectionPatch):
    require_feature(request, "connections")
    conn = writers.get_connection(connection_id)
    before = {"name": conn.name, "kind": conn.kind, "config": conn.config, "is_enabled": conn.is_enabled}
    if payload.name is not None:
        conn.name = payload.name.strip()
    if payload.kind is not None:
        conn.kind = payload.kind
    if payload.config is not None:
        conn.config = payload.config
    if payload.is_enabled is not None:
        conn.is_enabled = payload.is_enabled
    _check_kind(conn.kind, conn.config or {})
    try:
        with transaction.atomic():
            conn.save()
    except IntegrityError:
        raise Conflict("A connection with that name already exists", code="connection_name_taken") from None
    writers.close_connection(conn.id)
    writers.ensure_started(conn)
    changed = audit.fields_diff(before, {"name": conn.name, "kind": conn.kind, "config": conn.config, "is_enabled": conn.is_enabled}, ("name", "kind", "config", "is_enabled"))
    audit.record(request, "connection.update", conn, summary=audit.summarize_fields(changed), detail=changed)
    return _out(conn)


@router.delete("/connections/{connection_id}", response={204: None})
def delete_connection(request: HttpRequest, connection_id: int):
    require_feature(request, "connections")
    conn = writers.get_connection(connection_id)
    writers.close_connection(conn.id)
    audit.record(request, "connection.delete", conn, summary=conn.kind)
    conn.delete()
    return 204, None


@router.post("/connections/{connection_id}/test")
def test_connection(request: HttpRequest, connection_id: int):
    require_feature(request, "connections")
    conn = writers.get_connection(connection_id)
    try:
        writer = writers.open_connection(conn, force=True)
        return {"ok": True, "info": writer.info()}
    except Exception as exc:  # noqa: BLE001 — 測試端點要把失敗原因回給整合頁
        return {"ok": False, "error": str(exc)[:500]}


@router.post("/connections/{connection_id}/write")
def write_connection(request: HttpRequest, connection_id: int, payload: WriteIn):
    require_feature(request, "connections")
    conn = writers.get_connection(connection_id)
    if not payload.values:
        raise ValidationError("values cannot be empty", code="values_required")
    try:
        writer = writers.open_connection(conn)
        result = writer.write(payload.values, timeout=payload.timeout_s)
        return {"ok": True, "result": result, "info": writer.info()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}


@router.get("/connections/{connection_id}/state")
def connection_state(request: HttpRequest, connection_id: int, addresses: str = ""):
    principal(request)
    conn = writers.get_connection(connection_id)
    try:
        writer = writers.open_connection(conn)
        wanted = [a.strip() for a in addresses.split(",") if a.strip()]
        if not wanted and isinstance(writer, writers.DioSimWriter):
            return {"ok": True, "values": dict(writer.state), "info": writer.info()}
        return {"ok": True, "values": writer.read(wanted) if wanted else {}, "info": writer.info()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}
