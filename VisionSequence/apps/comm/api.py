"""通訊連線 API（掛在 /vision 底下）。

GET    /vision/connections/kinds
GET    /vision/connections                  任何登入者可讀
POST   /vision/connections                  管理員
GET    /vision/connections/{id}
PATCH  /vision/connections/{id}             管理員；設定變更會重開連線
DELETE /vision/connections/{id}             管理員
POST   /vision/connections/{id}/test        管理員：重新連線並回 info（失敗回 ok=false 與錯誤）
POST   /vision/connections/{id}/write       管理員：手動寫一筆 {"values": {"coil:0": 1}}
GET    /vision/connections/{id}/state       讀回 ?addresses=a,b
GET    /vision/connections/export           整份通訊設定（站台複製包；密碼欄位遮掉）
POST   /vision/connections/import           把匯出的檔案套到這一台
GET    /vision/integration/rules           站台接收規則（TCP 指令埠收到不是指令的一行時比對）
PATCH  /vision/integration/rules           管理員：整份取代

從站（`modbus_server`）與設了 `trigger_address` 的連線在建立／修改後會立刻開起來，
伺服器啟動時也會自動開（`writers.autostart()`，由 `manage.py serve` 呼叫）。
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from apps.accounts.security import principal, require_feature
from apps.comm import rules as rulemod, writers
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


class RulesIn(Schema):
    rules: list[dict[str, Any]]


#: 舊的扁平觸發設定；顯示時換成規則表，使用者一存檔就升級（`rules.rules_of` 兩種都讀得懂）。
_LEGACY_TRIGGER_KEYS = ("trigger_address", "trigger_flow", "trigger_mode", "trigger_clear", "trigger_done_address", "trigger_recipe")


def _shown_config(conn: Connection) -> dict[str, Any]:
    config = dict(conn.config or {})
    if "triggers" not in config:
        legacy = rulemod.from_legacy(config)
        if legacy:
            config["triggers"] = [r.as_dict() for r in legacy]
            for key in _LEGACY_TRIGGER_KEYS:
                config.pop(key, None)
    return config


def _out(conn: Connection) -> dict[str, Any]:
    return {
        "id": conn.id,
        "name": conn.name,
        "kind": conn.kind,
        "config": _shown_config(conn),
        "is_enabled": conn.is_enabled,
        "status": writers.connection_info(conn),
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }


def _check_kind(kind: str, config: dict[str, Any]) -> None:
    writers._resolve_class(kind, config)  # 未知 kind 直接 422


def _clean(config: dict[str, Any] | None) -> dict[str, Any]:
    """存檔前把觸發規則表正規化（壞掉的列丟掉，不讓設錯的一列害整條連線開不起來）。"""
    config = dict(config or {})
    if "triggers" in config:
        config["triggers"] = rulemod.sanitize(config.get("triggers"))
    return config


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
            conn = Connection.objects.create(name=name, kind=payload.kind, config=_clean(payload.config), is_enabled=payload.is_enabled)
    except IntegrityError:
        raise Conflict("A connection with that name already exists", code="connection_name_taken") from None
    writers.ensure_started(conn)  # 從站與觸發輪詢不必等到有人按「測試」
    audit.record(request, "connection.create", conn, summary=conn.kind, detail={"config": conn.config})
    return 201, _out(conn)


# ---------------------------------------------------------------------------
# 整份匯出匯入（站台複製包）
# ---------------------------------------------------------------------------
#: 匯出時要遮起來的設定欄位（名稱含這些字的一律換成 MASK）。
SECRET_HINTS = ("password", "secret", "token", "apikey", "api_key", "auth")
MASK = "***"
EXPORT_VERSION = 1


def _mask(config: dict[str, Any]) -> dict[str, Any]:
    """把看起來像密碼的欄位遮掉——設定檔會被寄來寄去，密碼不該跟著走。"""
    out: dict[str, Any] = {}
    for key, value in (config or {}).items():
        low = str(key).lower()
        out[key] = MASK if any(h in low for h in SECRET_HINTS) and value not in (None, "", 0) else value
    return out


def _unmask(config: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """匯入時把遮起來的欄位還原成這一台原本的值（沒有原本的值就留空）。"""
    out = dict(config or {})
    for key, value in list(out.items()):
        if value == MASK:
            if key in (existing or {}):
                out[key] = existing[key]
            else:
                out.pop(key)
    return out


class ImportIn(Schema):
    connections: list[dict[str, Any]] = []
    station_rules: list[dict[str, Any]] | None = None
    #: 同名的連線要不要覆蓋（False＝跳過，只建立新的）。
    overwrite: bool = True


@router.get("/connections/export")
def export_connections(request: HttpRequest):
    """整份通訊設定（連線、觸發規則表、站台接收規則）。複製一台站台就是匯出再匯入。"""
    require_feature(request, "connections")
    from apps.comm.models import StationRules

    row = StationRules.objects.filter(pk=1).first()
    return {
        "version": EXPORT_VERSION,
        "station_id": str(settings.VISION.get("STATION_ID", "")),
        "exported_at": timezone.now().isoformat(),
        "connections": [
            {"name": c.name, "kind": c.kind, "config": _mask(c.config or {}), "is_enabled": c.is_enabled}
            for c in Connection.objects.all()
        ],
        "station_rules": row.rules if row else [],
    }


@router.post("/connections/import")
def import_connections(request: HttpRequest, payload: ImportIn):
    """把匯出的檔案套到這一台。同名的連線預設覆蓋設定，其餘新建；沒帶到的連線不會被刪掉。

    被遮起來的密碼欄位（`***`）會還原成這一台原本的值——換句話說，複製設定不會把密碼洗掉。
    """
    require_feature(request, "connections")
    created, updated, skipped, failed = [], [], [], []
    for item in payload.connections[:200]:
        name = str((item or {}).get("name") or "").strip()
        kind = str((item or {}).get("kind") or "").strip()
        if not name or not kind:
            failed.append({"name": name, "error": "A name and a kind are required"})
            continue
        config = _clean((item or {}).get("config") or {})
        existing = Connection.objects.filter(name=name).first()
        if existing is not None and not payload.overwrite:
            skipped.append(name)
            continue
        try:
            _check_kind(kind, config)
        except Exception as exc:  # noqa: BLE001 — 一條壞掉不該讓整份匯入失敗
            failed.append({"name": name, "error": str(exc)[:200]})
            continue
        if existing is None:
            conn = Connection.objects.create(name=name, kind=kind, config=_unmask(config, {}),
                                             is_enabled=bool((item or {}).get("is_enabled", True)))
            created.append(name)
        else:
            existing.kind = kind
            existing.config = _unmask(config, existing.config or {})
            existing.is_enabled = bool((item or {}).get("is_enabled", existing.is_enabled))
            existing.save()
            writers.close_connection(existing.id)
            conn = existing
            updated.append(name)
        writers.ensure_started(conn)
    rules = None
    if payload.station_rules is not None:
        rules = rulemod.save_station_rules(payload.station_rules)
    audit.record(request, "connection.import", target_type="station",
                 summary=f"{len(created)} created, {len(updated)} updated",
                 detail={"created": created, "updated": updated, "skipped": skipped, "failed": failed})
    return {"created": created, "updated": updated, "skipped": skipped, "failed": failed,
            "station_rules": len(rules) if rules is not None else None}


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
        conn.config = _clean(payload.config)
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
        return {"ok": True, "values": writer.read(wanted) if wanted else {}, "info": writer.info()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}


# ---------------------------------------------------------------------------
# 站台接收規則（TCP 指令埠）
# ---------------------------------------------------------------------------
@router.get("/integration/rules")
def list_station_rules(request: HttpRequest):
    """站台層的接收規則：TCP 指令埠收到「不是指令」的一行時比對這一張表。"""
    principal(request)
    from apps.comm.models import StationRules

    row = StationRules.objects.filter(pk=1).first()
    return {"items": row.rules if row else [], "updated_at": row.updated_at.isoformat() if row else ""}


@router.patch("/integration/rules")
def save_station_rules(request: HttpRequest, payload: RulesIn):
    """整份取代（規則表在畫面上是一張表，逐列 PATCH 只會讓前端更難寫）。"""
    require_feature(request, "connections")
    saved = rulemod.save_station_rules(payload.rules)
    audit.record(request, "rules.update", target_type="station", summary=f"{len(saved)} rules", detail={"rules": saved})
    return {"items": saved}
