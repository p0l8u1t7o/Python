"""站台設定 API 與記憶體快取。

這裡照 retention 的模式：資料庫保存現場設定，`.env` 是出廠值，`effective()` 回傳記憶體快取，
`save()` 寫入後作廢並重建快取。runner 只讀 `effective()` 的快取結果，不在熱路徑查資料庫。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.accounts.security import require_admin
from apps.core import audit
from apps.core.errors import ValidationError
from apps.vision import versions
from apps.vision.models import Flow, VisionSettings

router = Router(tags=["vision-settings"])

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")
LOG_LEVELS = {
    "error": logging.ERROR,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE_LEVEL,
}

FIELDS: dict[str, type] = {
    "stable_cycle_mode": bool,
    "log_level": str,
    "auto_save_enabled": bool,
    "auto_save_interval_min": int,
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_last_auto_save = 0.0


def _default_log_level() -> str:
    raw = str(settings.VISION.get("LOG_LEVEL", "INFO") or "INFO").strip().lower()
    return raw if raw in LOG_LEVELS else "info"


def defaults() -> dict[str, Any]:
    """出廠值；沒有資料庫列或 migration 尚未完成時使用。"""
    return {
        "stable_cycle_mode": False,
        "log_level": _default_log_level(),
        "auto_save_enabled": False,
        "auto_save_interval_min": 15,
    }


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def effective() -> dict[str, Any]:
    """有效設定；有快取時不查資料庫，供 runner 熱路徑安全讀取。"""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
    values = defaults()
    try:
        row = VisionSettings.objects.filter(id=1).first()
    except Exception:  # noqa: BLE001 - migrate 前或測試切庫時先用出廠值
        row = None
    if row is not None:
        for key in FIELDS:
            values[key] = getattr(row, key)
    values["log_level"] = _clean_log_level(values.get("log_level"))
    values["auto_save_interval_min"] = max(1, int(values.get("auto_save_interval_min") or 15))
    with _lock:
        _cache = dict(values)
    return dict(values)


def _clean_log_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    if level not in LOG_LEVELS:
        raise ValueError(level)
    return level


def apply_log_level(level: str | None = None) -> int:
    """即時套用 Python logging 等級；trace 是比 DEBUG 更細的自訂等級 5。"""
    clean = _clean_log_level(level or effective()["log_level"])
    numeric = LOG_LEVELS[clean]
    logging.getLogger().setLevel(numeric)
    logging.getLogger("apps").setLevel(logging.NOTSET)
    return numeric


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """寫入設定並重建快取；未知欄位由 API 層擋下。"""
    clean: dict[str, Any] = {}
    if "stable_cycle_mode" in changes:
        clean["stable_cycle_mode"] = bool(changes["stable_cycle_mode"])
    if "log_level" in changes:
        clean["log_level"] = _clean_log_level(changes["log_level"])
    if "auto_save_enabled" in changes:
        clean["auto_save_enabled"] = bool(changes["auto_save_enabled"])
    if "auto_save_interval_min" in changes:
        clean["auto_save_interval_min"] = max(1, min(1440, int(changes["auto_save_interval_min"])))
    row, _ = VisionSettings.objects.get_or_create(id=1, defaults=defaults())
    for key, value in clean.items():
        setattr(row, key, value)
    row.save()
    invalidate()
    out = effective()
    if "log_level" in clean:
        apply_log_level(out["log_level"])
    return out


def status() -> dict[str, Any]:
    row = VisionSettings.objects.filter(id=1).first()
    return {
        "settings": effective(),
        "defaults": defaults(),
        "last_auto_save_at": row.last_auto_save_at.isoformat() if row and row.last_auto_save_at else None,
        "last_auto_save_result": (row.last_auto_save_result if row else None) or {},
    }


def auto_save_once(*, user=None) -> dict[str, Any]:
    """把所有流程存成版本；圖沒有變就跳過，避免擠掉手動版本。"""
    saved = 0
    skipped = 0
    for flow in Flow.objects.all().order_by("id"):
        latest = flow.versions.order_by("-version").first()
        graph = flow.graph or {}
        if latest is not None and latest.graph == graph:
            skipped += 1
            continue
        with transaction.atomic():
            locked = Flow.objects.select_for_update().get(pk=flow.pk)
            latest = locked.versions.order_by("-version").first()
            graph = locked.graph or {}
            if latest is not None and latest.graph == graph:
                skipped += 1
                continue
            if latest is not None:
                locked.version = max(int(locked.version), int(latest.version)) + 1
                locked.save(update_fields=["version", "updated_at"])
            versions.snapshot(locked, user=user, note="auto save")
            saved += 1
    result = {"saved": saved, "skipped": skipped, "flows": saved + skipped}
    VisionSettings.objects.get_or_create(id=1, defaults=defaults())[0]
    VisionSettings.objects.filter(id=1).update(last_auto_save_at=timezone.now(), last_auto_save_result=result)
    return result


def maybe_auto_save() -> dict[str, Any] | None:
    """背景執行緒週期性呼叫；設定關閉時完全不動。"""
    global _last_auto_save
    cfg = effective()
    if not cfg["auto_save_enabled"]:
        return None
    interval_s = max(60, int(cfg["auto_save_interval_min"]) * 60)
    now = time.monotonic()
    if now - _last_auto_save < interval_s:
        return None
    _last_auto_save = now
    try:
        return auto_save_once()
    except Exception:  # noqa: BLE001 - 背景工作不能讓 persister 停掉
        logging.getLogger(__name__).exception("自動儲存流程版本失敗")
        return None


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(body, dict):
        raise ValidationError("A JSON object is required", code="bad_body")
    return body


def _unknown(body: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(body) - allowed)
    if extra:
        raise ValidationError(f"Unknown setting: {', '.join(extra)}", code="bad_field", details={"fields": extra})


@router.get("/settings/execution")
def execution_status(request: HttpRequest):
    """Execution strategy settings; administrators only."""
    require_admin(request)
    return {"settings": effective(), "capacity": _capacity_snapshot()}


@router.patch("/settings/execution")
def execution_patch(request: HttpRequest):
    """Toggle stable-cycle mode; it takes effect without restart."""
    require_admin(request)
    body = _body(request)
    _unknown(body, {"stable_cycle_mode"})
    saved = save(body)
    audit.record(request, "settings.execution", target_type="settings", target_name="execution",
                 summary=f"stable_cycle_mode={saved['stable_cycle_mode']}", detail=saved)
    return {"settings": saved, "capacity": _capacity_snapshot()}


@router.get("/settings/log-level")
def log_level_status(request: HttpRequest):
    """Current Python log level; trace is a custom level below DEBUG and is intentionally noisy."""
    require_admin(request)
    cfg = effective()
    return {"level": cfg["log_level"], "levels": list(LOG_LEVELS), "effective": logging.getLogger().getEffectiveLevel()}


@router.patch("/settings/log-level")
def log_level_patch(request: HttpRequest):
    """Change Python logging level immediately."""
    p = require_admin(request)
    body = _body(request)
    _unknown(body, {"level", "log_level"})
    raw = body.get("level", body.get("log_level"))
    try:
        saved = save({"log_level": raw})
    except ValueError:
        raise ValidationError("Log level must be error, info, debug or trace", code="bad_log_level") from None
    audit.record(request, "settings.log_level", target_type="settings", target_name="log-level",
                 summary=f"log_level={saved['log_level']}", detail={"level": saved["log_level"], "actor": p.name})
    return {"level": saved["log_level"], "effective": logging.getLogger().getEffectiveLevel()}


@router.get("/settings/auto-save")
def auto_save_status(request: HttpRequest):
    """Auto Save Solution status; administrators only."""
    require_admin(request)
    return status()


@router.patch("/settings/auto-save")
def auto_save_patch(request: HttpRequest):
    """Change Auto Save Solution schedule."""
    require_admin(request)
    body = _body(request)
    _unknown(body, {"auto_save_enabled", "auto_save_interval_min"})
    try:
        saved = save(body)
    except (TypeError, ValueError):
        raise ValidationError("Auto-save interval must be a whole number of minutes", code="bad_value") from None
    audit.record(request, "settings.auto_save", target_type="settings", target_name="auto-save",
                 summary=f"enabled={saved['auto_save_enabled']}, interval={saved['auto_save_interval_min']}m", detail=saved)
    return status()


@router.post("/settings/auto-save/run")
def auto_save_run(request: HttpRequest):
    """Run Auto Save Solution once now."""
    p = require_admin(request)
    result = auto_save_once(user=p.user)
    audit.record(request, "settings.auto_save.run", target_type="settings", target_name="auto-save",
                 summary=f"saved {result['saved']} flows, skipped {result['skipped']}", detail=result)
    return {"result": result, "status": status()}


def _capacity_snapshot() -> dict[str, Any]:
    from apps.vision.runner import runner

    return runner.capacity()


try:
    apply_log_level()
except Exception:  # noqa: BLE001 - migration 前匯入時保留 settings.py 的 LOGGING
    pass
