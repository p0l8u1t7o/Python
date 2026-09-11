"""流程的穩定序列化（匯出／匯入），給 CLI `manage.py flow` 與 API 共用。

匯出格式（schema_version 1）：
- key 固定順序：schema_version, exported_at, name, description, continuous_interval_ms, graph
- graph.nodes 依 id 排序、graph.edges 依 (source, target, source_handle, target_handle) 排序
- 節點 key 固定順序（id, type, label, description, enabled, continue_on_error, color, params, position, width, height，
  其餘依字母序）；params 依 key 排序；position 四捨五入為整數
- image_source.source_id 換成 {SOURCE} 佔位符（複用範本庫的 templatize）
- 2 空格縮排、ensure_ascii=False、UTF-8 無 BOM、LF、檔尾一個換行

設定環境變數 SOURCE_DATE_EPOCH（reproducible-builds 慣例）可固定 exported_at，讓兩次匯出 byte-identical。
DB 仍是執行期權威來源；匯入依 name upsert。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.core.errors import Conflict, ValidationError
from apps.vision.api_more import instantiate, templatize
from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow

SCHEMA_VERSION = 1
DOC_KEYS = ("schema_version", "exported_at", "name", "description", "continuous_interval_ms", "graph", "fixed_images", "assets", "asset_warnings", "composite_tools")
NODE_KEYS = ("id", "type", "label", "description", "enabled", "continue_on_error", "color", "params", "position", "width", "height")
EDGE_KEYS = ("id", "source", "source_handle", "target", "target_handle")
ASSET_REPORT_KEY = "_asset_import"
COMPOSITE_REPORT_KEY = "_composite_import"


def _ordered(obj: dict[str, Any], first: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in first:
        if k in obj:
            out[k] = obj[k]
    for k in sorted(k for k in obj if k not in first):
        out[k] = obj[k]
    return out


def _sorted_json(value: Any) -> Any:
    """巢狀 dict 依 key 排序（params 內容可能有 ROI 物件等）。"""
    if isinstance(value, dict):
        return {k: _sorted_json(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted_json(v) for v in value]
    return value


def _round_position(pos: Any) -> Any:
    if not isinstance(pos, dict):
        return pos
    out = {}
    for k in ("x", "y"):
        v = pos.get(k, 0)
        try:
            out[k] = int(round(float(v)))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def normalize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """排序、固定 key 順序、位置取整；不換佔位符。回傳新物件。"""
    graph = validate_graph(json.loads(json.dumps(graph or {"nodes": [], "edges": []})))
    nodes = []
    for n in sorted(graph.get("nodes", []), key=lambda n: str(n.get("id"))):
        n = dict(n)
        if "params" in n:
            n["params"] = _sorted_json(n.get("params") or {})
        if "position" in n:
            n["position"] = _round_position(n["position"])
        for k in ("width", "height"):
            if k in n and isinstance(n[k], (int, float)):
                n[k] = int(round(n[k]))
        nodes.append(_ordered(n, NODE_KEYS))
    edges = []
    for e in sorted(graph.get("edges", []), key=lambda e: (str(e.get("source")), str(e.get("target")), str(e.get("source_handle") or ""), str(e.get("target_handle") or ""))):
        edges.append(_ordered(dict(e), EDGE_KEYS))
    return {"nodes": nodes, "edges": edges}


def _exported_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    else:
        dt = datetime.now(tz=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def export_flow(flow: Flow, *, include_assets: bool = False) -> dict[str, Any]:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _exported_at(),
        "name": flow.name,
        "description": flow.description or "",
        "continuous_interval_ms": int(flow.continuous_interval_ms or 0),
        "graph": normalize_graph(templatize(flow.graph or {"nodes": [], "edges": []})),
    }
    # 只有圖裡真的用到固定影像才帶（沒有的流程維持原本的匯出格式）
    pictures = _fixed_images_payload(flow.graph or {})
    if pictures:
        doc["fixed_images"] = pictures
    if include_assets:
        assets, warnings = _assets_payload(flow.graph or {})
        doc["assets"] = assets
        if warnings["skipped"]:
            doc["asset_warnings"] = warnings
    # 用到的複合工具一起帶走（含巢狀），匯入端沒有就建起來（PRODUCT-DIRECTION v2 §3-8）
    from apps.vision import composites

    deps = composites.dependency_docs(flow.graph or {})
    if deps:
        doc["composite_tools"] = deps
    return {k: doc[k] for k in DOC_KEYS if k in doc}


def _fixed_images_payload(graph: dict[str, Any]) -> dict[str, str]:
    """流程引用的固定影像（PNG base64）：匯出檔自給自足，匯入到別台也跑得起來。"""
    import base64

    from apps.vision import fixed_images

    out: dict[str, str] = {}
    for image_id in sorted(fixed_images.ids_in_graph(graph)):
        try:
            with open(fixed_images.path_of(image_id), "rb") as fh:
                out[image_id] = base64.b64encode(fh.read()).decode("ascii")
        except (OSError, fixed_images.FixedImageError):
            continue
    return out


def restore_fixed_images(doc: dict[str, Any]) -> int:
    """匯入：把文件裡的固定影像寫回檔案庫（內容雜湊命名，id 不變）。回寫入張數。"""
    import base64

    from apps.vision import fixed_images

    n = 0
    for image_id, b64 in (doc.get("fixed_images") or {}).items():
        try:
            desc = fixed_images.store_bytes(base64.b64decode(b64))
        except (ValueError, fixed_images.FixedImageError):
            continue
        if desc["id"] == image_id:
            n += 1
    return n


def _uuid_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        return ""


def _asset_ids_in_graph(graph: dict[str, Any] | None) -> dict[str, set[str]]:
    """掃流程參數裡看起來像 UUID 的字串；是否真是資產稍後交給資料庫確認。"""
    out: dict[str, set[str]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, str):
            key = _uuid_text(value)
            if key:
                out.setdefault(key, set()).add(value)
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)

    for node in (graph or {}).get("nodes") or []:
        visit((node.get("params") or {}))
    return out


def _sha256_file(path: str) -> str:
    digest = __import__("hashlib").sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mb(size: int) -> float:
    return round(size / (1024 * 1024), 3)


def _assets_payload(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """流程引用的 Asset 內嵌封包；總量超過上限時略過並在文件中列明。"""
    import base64

    refs = _asset_ids_in_graph(graph)
    rows = list(Asset.objects.filter(pk__in=refs).order_by("id"))
    max_mb = int(getattr(settings, "VISION_EXPORT_MAX_MB", 200) or 0)
    limit = max(0, max_mb) * 1024 * 1024
    total = 0
    embedded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for asset in rows:
        try:
            size = int(os.path.getsize(asset.path))
            sha = _sha256_file(asset.path)
        except OSError:
            skipped.append({"id": str(asset.id), "name": asset.name, "kind": asset.kind, "size": int(asset.size or 0), "reason": "missing_file"})
            continue
        total += size
        if size > limit or total > limit:
            skipped.append({"id": str(asset.id), "name": asset.name, "kind": asset.kind, "size": size, "sha256": sha, "reason": "export_size_limit"})
            continue
        with open(asset.path, "rb") as fh:
            data = fh.read()
        embedded.append({
            "id": str(asset.id),
            "kind": asset.kind,
            "name": asset.name,
            "sha256": sha,
            "size": len(data),
            "extension": os.path.splitext(asset.path)[1].lower(),
            "group": asset.group,
            "meta": asset.meta or {},
            "data": base64.b64encode(data).decode("ascii"),
        })
    return embedded, {
        "max_mb": max_mb,
        "total_mb": _mb(total),
        "skipped_mb": _mb(sum(int(item.get("size") or 0) for item in skipped)),
        "skipped": skipped,
    }


def _existing_assets_by_sha() -> dict[str, Asset]:
    found: dict[str, Asset] = {}
    for asset in Asset.objects.all().order_by("created_at"):
        try:
            sha = _sha256_file(asset.path)
        except OSError:
            continue
        found.setdefault(sha, asset)
    return found


def _safe_extension(value: Any) -> str:
    ext = os.path.splitext(str(value or ""))[1].lower()
    if 1 < len(ext) <= 10 and ext[1:].replace("_", "").isalnum():
        return ext
    return ".bin"


def _replace_asset_ids(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        key = _uuid_text(value)
        return id_map.get(value) or (id_map.get(key) if key else None) or value
    if isinstance(value, list):
        return [_replace_asset_ids(item, id_map) for item in value]
    if isinstance(value, dict):
        return {k: _replace_asset_ids(v, id_map) for k, v in value.items()}
    return value


def restore_assets(doc: dict[str, Any]) -> dict[str, Any]:
    """匯入內嵌資產：以 sha256 去重，並把流程參數裡的舊 Asset id 換成本機 id。"""
    import base64

    refs = _asset_ids_in_graph(doc.get("graph") or {})
    embedded = {str(item.get("id") or ""): item for item in (doc.get("assets") or []) if isinstance(item, dict)}
    existing_by_sha = _existing_assets_by_sha()
    id_map: dict[str, str] = {}
    report: dict[str, Any] = {"restored": [], "reused": [], "missing": []}

    for old_id, item in sorted(embedded.items()):
        old_key = _uuid_text(old_id)
        if old_key not in refs:
            continue
        try:
            data = base64.b64decode(str(item.get("data") or ""), validate=True)
        except (ValueError, TypeError):
            report["missing"].append({"id": old_id, "name": str(item.get("name") or ""), "kind": str(item.get("kind") or ""), "reason": "bad_data"})
            continue
        sha = __import__("hashlib").sha256(data).hexdigest()
        if sha != str(item.get("sha256") or "") or len(data) != int(item.get("size") or len(data)):
            report["missing"].append({"id": old_id, "name": str(item.get("name") or ""), "kind": str(item.get("kind") or ""), "reason": "checksum_mismatch"})
            continue
        asset = existing_by_sha.get(sha)
        if asset is None:
            asset_id = uuid.uuid4()
            ext = _safe_extension(item.get("extension") or item.get("name"))
            path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}{ext}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            asset = Asset.objects.create(
                id=asset_id,
                name=str(item.get("name") or asset_id.hex)[:200],
                kind=str(item.get("kind") or "file")[:20],
                group=str(item.get("group") or "")[:60],
                path=path,
                size=len(data),
                meta=dict(item.get("meta") or {}),
            )
            existing_by_sha[sha] = asset
            report["restored"].append({"old_id": old_id, "id": str(asset.id), "name": asset.name, "kind": asset.kind, "sha256": sha, "size": len(data)})
        else:
            report["reused"].append({"old_id": old_id, "id": str(asset.id), "name": asset.name, "kind": asset.kind, "sha256": sha, "size": int(asset.size or len(data))})
        id_map[old_id] = str(asset.id)
        id_map[old_key] = str(asset.id)
        id_map[old_key.replace("-", "")] = str(asset.id)

    for old_key, tokens in refs.items():
        if old_key in id_map:
            continue
        if Asset.objects.filter(pk=old_key).exists():
            continue
        item = embedded.get(old_key) or embedded.get(old_key.replace("-", ""))
        report["missing"].append({
            "id": sorted(tokens)[0],
            "name": str((item or {}).get("name") or ""),
            "kind": str((item or {}).get("kind") or ""),
            "reason": "not_embedded",
        })
    if id_map:
        doc["graph"] = _replace_asset_ids(doc.get("graph") or {}, id_map)
    doc[ASSET_REPORT_KEY] = report
    return report


def asset_import_report(doc: dict[str, Any]) -> dict[str, Any]:
    return dict(doc.get(ASSET_REPORT_KEY) or {"restored": [], "reused": [], "missing": []})


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def to_bytes(doc: dict[str, Any]) -> bytes:
    return dumps(doc).replace("\r\n", "\n").encode("utf-8")


def write_file(doc: dict[str, Any], path: str) -> None:
    with open(path, "wb") as f:
        f.write(to_bytes(doc))


def parse_any(text: str | bytes) -> Any:
    """只做 JSON 解碼（.tool.json 這類其他文件自己驗證形狀）。"""
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Not valid JSON: {exc}", code="bad_json") from None


def parse(text: str | bytes) -> dict[str, Any]:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Not valid JSON: {exc}", code="bad_json") from None
    if not isinstance(doc, dict):
        raise ValidationError("A flow file must be an object", code="bad_flow_file")
    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValidationError(f"Unsupported schema_version {version!r} (this build uses {SCHEMA_VERSION})", code="bad_schema_version")
    name = str(doc.get("name") or "").strip()
    if not name:
        raise ValidationError("The flow file has no name", code="bad_flow_file")
    if not isinstance(doc.get("graph"), dict):
        raise ValidationError("The flow file has no graph", code="bad_flow_file")
    return doc


def materialize_graph(doc: dict[str, Any], *, source_id: int | None) -> dict[str, Any]:
    """把 {SOURCE} 換成來源 id（未給則留空字串）並驗證。"""
    return validate_graph(instantiate(doc["graph"], source_id=source_id))


def _carry_over_sources(graph: dict[str, Any], existing: dict[str, Any]) -> None:
    """更新既有流程且沒指定 source_id：取像步驟沿用原流程的來源（同 id 優先，否則任一取像步驟的來源），
    不要把現場已設好的來源清成空白。"""
    old_by_id = {n.get("id"): n for n in existing.get("nodes", []) if n.get("type") == "image_source"}
    fallback = next((n.get("params", {}).get("source_id") for n in old_by_id.values() if n.get("params", {}).get("source_id") not in ("", None)), None)
    for node in graph.get("nodes", []):
        if node.get("type") != "image_source":
            continue
        params = node.setdefault("params", {})
        if params.get("source_id") not in ("", None):
            continue
        old = old_by_id.get(node.get("id"))
        old_sid = old.get("params", {}).get("source_id") if old else None
        params["source_id"] = old_sid if old_sid not in ("", None) else (fallback if fallback is not None else "")


def import_flow(doc: dict[str, Any], *, source_id: int | None = None, owner=None) -> tuple[Flow, bool]:
    """依 name upsert：存在則更新 graph／description／間隔並 version+1；不存在則建立。
    更新既有流程且未指定 source_id 時，取像步驟沿用原流程的來源。"""
    restore_fixed_images(doc)
    restore_assets(doc)
    from apps.vision import composites

    doc[COMPOSITE_REPORT_KEY] = composites.import_dependencies(owner, doc)
    graph = materialize_graph(doc, source_id=source_id)
    name = str(doc["name"]).strip()
    description = str(doc.get("description") or "")
    interval = max(0, int(doc.get("continuous_interval_ms") or 0))
    try:
        with transaction.atomic():
            flow = Flow.objects.filter(name=name).first()
            if flow is None:
                flow = Flow.objects.create(name=name, description=description, graph=graph, owner=owner, continuous_interval_ms=interval)
                return flow, True
            if source_id is None:
                _carry_over_sources(graph, flow.graph or {})
            flow.graph = graph
            flow.description = description
            flow.continuous_interval_ms = interval
            flow.version += 1
            flow.save()
            return flow, False
    except IntegrityError:
        raise Conflict("A flow with that name already exists", code="flow_name_taken") from None


def find_flow(ref: str) -> Flow | None:
    """`<id|name>`：純數字先當 id。"""
    ref = str(ref).strip()
    if ref.isdigit():
        flow = Flow.objects.filter(pk=int(ref)).first()
        if flow is not None:
            return flow
    return Flow.objects.filter(name=ref).first()


__all__ = [
    "SCHEMA_VERSION", "export_flow", "normalize_graph", "dumps", "to_bytes", "write_file", "parse",
    "materialize_graph", "import_flow", "find_flow", "restore_assets", "asset_import_report",
]
