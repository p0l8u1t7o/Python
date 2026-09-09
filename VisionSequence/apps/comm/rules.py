"""觸發規則表：設備做了什麼 → 平台做什麼。

以前一條連線只能設一組 `trigger_*`（一個位址 → 一條流程）。現場很快就不夠用：
同一台控制器常常一個位址觸發檢測、另一個位址換配方、再一個位址要平台鎖住硬體讓維修人員動手。
規則表把「來源 → 動作」變成一張可以有很多列的表：

    來源 value：讀一個位址，比對方式 rising／falling／change／nonzero／equal／not_equal／range
    來源 text ：收到一行文字，比對方式 exact／contains／prefix／regex（regex 的群組可帶進流程）
    動作      ：run_flow（帶 lot／sn 等引數）／activate_recipe（換線）／set_variable／set_param／calibration_signal／lock／unlock

規則存在 `Connection.config["triggers"]`（陣列）；舊的扁平 `trigger_*` 鍵由 `rules_of()` 包成
單一規則，所以既有站台不必改設定就照常運作。文字規則另外存在站台層（`StationRules`），
給 TCP 指令埠收到「不是指令」的一行時比對——條碼槍直接把料號送進來就是這一種。

**這一層只認得規則，不認得連線**：比對是純函式（好測、也給之後的串口／UDP 連線共用），
真正動手的 `fire()` 才碰 runner 與資料庫。規則壞掉一律丟掉那一列而不是拋例外——
一條設錯的規則不該讓整頁連線打不開。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: 來源：讀位址的值，或收到的一行文字。
SOURCES = ("value", "text")
#: 值的比對方式。rising／falling／change 看的是**變化**，nonzero 看的是**當下的位準**
#: （只要還是非零就一直觸發，沿用舊設定的語意）；equal／not_equal／range 是「條件成立的那一刻」
#: 觸發一次，不會在條件持續成立時每次輪詢都跑一遍。
VALUE_MODES = ("rising", "falling", "change", "nonzero", "equal", "not_equal", "range")
#: 邊緣型（條件由不成立變成成立才觸發一次）。
EDGE_MODES = ("rising", "falling", "change", "equal", "not_equal", "range")
#: 文字的比對方式。
TEXT_MATCHES = ("exact", "contains", "prefix", "regex")
#: 動作。
ACTIONS = ("run_flow", "activate_recipe", "set_variable", "set_param", "calibration_signal", "lock", "unlock")
SCOPES = ("flow", "station")
SIGNAL_KINDS = ("start", "point", "end", "teach")

#: 規則名稱與引數名稱的長度上限（設定是人打的，擋住離譜的值就好）。
MAX_TEXT = 300
MAX_RULES = 50


class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass(frozen=True)
class Rule:
    """一條規則。欄位一律有預設值——規則表是使用者填的，缺欄位要能用而不是炸掉。"""

    id: str = ""
    name: str = ""
    enabled: bool = True
    source: str = "value"
    # -- 值來源 --
    address: str = ""
    mode: str = "rising"
    value: float = 0.0
    value2: float = 0.0
    # -- 文字來源 --
    match: str = "contains"
    pattern: str = ""
    capture: str = ""
    # -- 動作 --
    action: str = "run_flow"
    flow: str = ""
    recipe: str = ""
    variable: str = ""
    node: str = ""
    param: str = ""
    scope: str = "flow"
    set_value: str = ""
    signal_kind: str = "point"
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    ttl: int = 0
    # -- 握手（值來源） --
    clear: bool = False
    done: str = ""
    # -- 回覆（文字來源） --
    reply: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled, "source": self.source,
            "address": self.address, "mode": self.mode, "value": self.value, "value2": self.value2,
            "match": self.match, "pattern": self.pattern, "capture": self.capture,
            "action": self.action, "flow": self.flow, "recipe": self.recipe,
            "variable": self.variable, "node": self.node, "param": self.param,
            "scope": self.scope, "set_value": self.set_value, "signal_kind": self.signal_kind, "args": dict(self.args),
            "reason": self.reason, "ttl": self.ttl, "clear": self.clear, "done": self.done, "reply": self.reply,
        }

    def label(self) -> str:
        """規則的一行說明（給追蹤紀錄與狀態用）。"""
        if self.name:
            return self.name
        where = f"{self.address} {self.mode}" if self.source == "value" else f"{self.match} '{self.pattern}'"
        target = self.flow or self.variable or self.recipe or self.node or self.signal_kind or self.action
        return f"{where} -> {self.action} {target}".strip()


# ---------------------------------------------------------------------------
# 讀設定
# ---------------------------------------------------------------------------
def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _raw_text(value: Any, limit: int = MAX_TEXT) -> str:
    """不去頭尾空白的欄位：樣式（`SCAN ` 的尾巴那一格是規則的一部分）、回覆樣板、要存的值。"""
    return str(value if value is not None else "")[:limit]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _rule_from(raw: Any, index: int) -> Rule | None:
    """一列設定 → Rule；缺了該有的欄位就回 None（丟掉這一列，其他規則照常）。"""
    if not isinstance(raw, dict):
        return None
    source = _pick(raw.get("source"), SOURCES, "value")
    action = _pick(raw.get("action"), ACTIONS, "run_flow")
    rule = Rule(
        id=_text(raw.get("id")) or f"r{index + 1}",
        name=_text(raw.get("name"), 80),
        enabled=bool(raw.get("enabled", True)),
        source=source,
        address=_text(raw.get("address"), 80),
        mode=_pick(raw.get("mode"), VALUE_MODES, "rising"),
        value=_number(raw.get("value")),
        value2=_number(raw.get("value2")),
        match=_pick(raw.get("match"), TEXT_MATCHES, "contains"),
        pattern=_raw_text(raw.get("pattern")),
        capture=_text(raw.get("capture"), 40),
        action=action,
        flow=_text(raw.get("flow"), 120),
        recipe=_text(raw.get("recipe"), 120),
        variable=_text(raw.get("variable"), 60),
        node=_text(raw.get("node"), 80),
        param=_text(raw.get("param"), 80),
        scope=_pick(raw.get("scope"), SCOPES, "flow"),
        set_value=_raw_text(raw.get("set_value")),
        signal_kind=_pick(raw.get("signal_kind"), SIGNAL_KINDS, "point"),
        args={str(k)[:40]: v for k, v in (raw.get("args") or {}).items()} if isinstance(raw.get("args"), dict) else {},
        reason=_text(raw.get("reason")),
        ttl=max(0, int(_number(raw.get("ttl")))),
        clear=bool(raw.get("clear", False)),
        done=_text(raw.get("done"), 80),
        reply=_raw_text(raw.get("reply"), 500),
    )
    if source == "value" and not rule.address:
        return None
    if source == "text" and not rule.pattern:
        return None
    if rule.source == "text" and rule.match == "regex":
        try:
            re.compile(rule.pattern)
        except re.error:
            return None
    if action in ("run_flow", "activate_recipe") and not rule.flow:
        return None
    if action == "activate_recipe" and not rule.recipe:
        return None
    if action == "set_variable" and not rule.variable:
        return None
    if action == "set_variable" and rule.scope == "flow" and not rule.flow:
        return None
    if action == "set_param" and (not rule.flow or not rule.node or not rule.param):
        return None
    return rule


def sanitize(raw: Any) -> list[dict[str, Any]]:
    """存檔前正規化：丟掉壞掉的列、補齊欄位、限制數量。回可以直接存進 JSON 欄位的形狀。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw[:MAX_RULES]):
        rule = _rule_from(item, i)
        if rule is None:
            continue
        ident = rule.id if rule.id not in seen else f"r{i + 1}"
        seen.add(ident)
        out.append(Rule(**{**rule.as_dict(), "id": ident, "args": dict(rule.args)}).as_dict())
    return out


def parse(raw: Any) -> list[Rule]:
    """設定 → Rule 清單（只留 enabled 的由呼叫端自己過濾）。"""
    out: list[Rule] = []
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw[:MAX_RULES]):
        rule = _rule_from(item, i)
        if rule is not None:
            out.append(rule)
    return out


def from_legacy(config: dict[str, Any]) -> list[Rule]:
    """舊的扁平 `trigger_*` 設定 → 單一規則（既有站台不必改設定）。"""
    address = _text((config or {}).get("trigger_address"), 80)
    flow = _text((config or {}).get("trigger_flow"), 120)
    if not address or not flow:
        return []
    mode = "nonzero" if str((config or {}).get("trigger_mode") or "").lower() == "nonzero" else "rising"
    return [Rule(
        id="legacy", name="", enabled=True, source="value", address=address, mode=mode,
        action="run_flow", flow=flow, recipe=_text(config.get("trigger_recipe"), 120),
        clear=bool(config.get("trigger_clear", True)), done=_text(config.get("trigger_done_address"), 80),
    )]


def rules_of(config: dict[str, Any]) -> list[Rule]:
    """連線設定 → 啟用中的規則。有 `triggers` 就用它，否則退回舊的扁平設定。"""
    config = config or {}
    listed = parse(config.get("triggers"))
    if not listed and "triggers" not in config:
        listed = from_legacy(config)
    return [r for r in listed if r.enabled]


def watched_addresses(rules: list[Rule]) -> list[str]:
    """要輪詢的位址（去重、保持順序）——一次 `read()` 讀完，不要一條規則讀一次。"""
    out: list[str] = []
    for rule in rules:
        if rule.source == "value" and rule.address and rule.address not in out:
            out.append(rule.address)
    return out


# ---------------------------------------------------------------------------
# 比對（純函式）
# ---------------------------------------------------------------------------
def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "0", "false", "False")
    return bool(value)


def _holds(rule: Rule, value: Any) -> bool:
    """條件在「這一刻」是否成立（不看之前的值）。"""
    if rule.mode in ("rising", "nonzero"):
        return _truthy(value)
    if rule.mode == "falling":
        return not _truthy(value)
    if rule.mode == "equal":
        return _number(value, float("nan")) == rule.value
    if rule.mode == "not_equal":
        return _number(value, float("nan")) != rule.value
    if rule.mode == "range":
        low, high = (rule.value, rule.value2) if rule.value <= rule.value2 else (rule.value2, rule.value)
        return low <= _number(value, float("nan")) <= high
    return False


def match_value(rule: Rule, previous: Any, current: Any) -> bool:
    """值來源要不要觸發。`previous` 是上一輪讀到的值（第一輪傳 None）。

    nonzero 是位準（只要非零就一直回 True）；其餘都是邊緣——條件由不成立變成成立才回一次 True。
    `change` 只要值變了就觸發，所以第一輪（沒有前值）不觸發。
    """
    if rule.mode == "nonzero":
        return _truthy(current)
    if rule.mode == "change":
        return previous is not None and current != previous
    now = _holds(rule, current)
    if not now:
        return False
    return previous is None or not _holds(rule, previous)


def match_text(rule: Rule, line: str) -> dict[str, Any] | None:
    """文字來源：不相符回 None，相符回要帶進流程的引數（可能是空的 dict）。

    `capture` 給抓到的內容一個名字：regex 用第一個群組（沒有群組就整段），prefix 用前綴之後的部分，
    exact／contains 用整行。regex 的具名群組不管有沒有設 capture 都會帶進去。
    """
    text = (line or "").strip()
    if not rule.pattern:
        return None
    captured: dict[str, Any] = {}
    if rule.match == "exact":
        if text != rule.pattern:
            return None
        taken = text
    elif rule.match == "contains":
        if rule.pattern not in text:
            return None
        taken = text
    elif rule.match == "prefix":
        if not text.startswith(rule.pattern):
            return None
        taken = text[len(rule.pattern):].strip()
    else:
        try:
            found = re.search(rule.pattern, text)
        except re.error:
            return None
        if found is None:
            return None
        captured.update({k: v for k, v in (found.groupdict() or {}).items() if v is not None})
        taken = found.group(1) if found.re.groups and found.group(1) is not None else found.group(0)
    if rule.capture:
        captured[rule.capture] = taken
    return captured


def render(template: str, values: dict[str, Any]) -> str:
    r"""回覆樣板：`{名字}` 取值，取不到留空（產線優先，缺一個量測值不該讓設備收到例外）。

    使用者在欄位裡打的 `
` `
` `	` 會轉成真的控制字元，與「格式化回覆」工具同一個規則。
    """
    from apps.comm.protocol import unescape

    try:
        return unescape(template).format_map(_Missing(values))
    except (ValueError, IndexError):  # 樣板本身寫壞（例如落單的大括號）
        return unescape(template)


# ---------------------------------------------------------------------------
# 站台層的文字規則（TCP 指令埠收到不是指令的一行時比對）
# ---------------------------------------------------------------------------
#: 記憶體快取——指令埠每一行都要比對，不能每次查資料庫。改規則的端點會作廢它。
_station: list[Rule] | None = None


def invalidate() -> None:
    global _station
    _station = None


def station_rules() -> list[Rule]:
    """站台層的文字規則（只回啟用中的）。資料庫讀不到時回空清單，指令埠照常運作。"""
    global _station
    if _station is None:
        try:
            from apps.comm.models import StationRules

            row = StationRules.objects.filter(pk=1).first()
            _station = [r for r in parse(row.rules if row else []) if r.enabled and r.source == "text"]
        except Exception:  # noqa: BLE001 — 規則讀不到不該讓 TCP 指令埠停擺
            log.warning("站台接收規則讀取失敗", exc_info=True)
            return []
    return _station


def save_station_rules(raw: Any) -> list[dict[str, Any]]:
    """存站台層規則（只收文字規則——指令埠沒有位址可以讀）並作廢快取。回存進去的形狀。"""
    from apps.comm.models import StationRules

    cleaned = [r for r in sanitize(raw) if r["source"] == "text"]
    row, _ = StationRules.objects.get_or_create(pk=1)
    row.rules = cleaned
    row.save(update_fields=["rules", "updated_at"])
    invalidate()
    return cleaned


# ---------------------------------------------------------------------------
# 動作（碰 runner 與資料庫）
# ---------------------------------------------------------------------------
def find_flow(ident: str):
    from apps.vision.models import Flow

    qs = Flow.objects.filter(pk=int(ident)) if ident.isdigit() else Flow.objects.filter(name=ident)
    return qs.filter(is_enabled=True).first()


def _rule_value(rule: Rule, context: dict[str, Any]) -> str:
    """取規則要寫入的值；樣板可使用文字規則抓到的欄位。"""
    return render(rule.set_value, context) if "{" in rule.set_value else rule.set_value


def _find_node(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in (graph or {}).get("nodes", []):
        if isinstance(node, dict) and str(node.get("id") or "") == node_id:
            return node
    return None


def _set_param(rule: Rule, context: dict[str, Any], *, find_flow=find_flow) -> dict[str, Any]:
    """把整合端送來的值寫進預設配方；只允許現場教導參數。"""
    flow = find_flow(rule.flow)
    if flow is None:
        return {"ok": False, "action": rule.action, "summary": f"Flow '{rule.flow}' does not exist or is disabled", "detail": {}}
    node = _find_node(flow.graph, rule.node)
    if node is None:
        return {"ok": False, "action": rule.action, "summary": f"Node '{rule.node}' does not exist", "detail": {"flow": flow.name}}
    try:
        from apps.vision.tools import base, register_builtins

        register_builtins()
        tool = base.get(str(node.get("type") or ""))
    except Exception:  # noqa: BLE001 — 工具登錄異常要回規則失敗，不讓接收端斷線
        return {"ok": False, "action": rule.action, "summary": f"Tool '{node.get('type')}' does not exist", "detail": {"flow": flow.name, "node": rule.node}}
    spec = next((p for p in getattr(tool, "params", ()) or () if p.key == rule.param), None)
    if spec is None:
        return {"ok": False, "action": rule.action, "summary": f"Parameter '{rule.param}' does not exist", "detail": {"flow": flow.name, "node": rule.node}}
    if not bool(getattr(spec, "teach", False)):
        return {"ok": False, "action": rule.action, "summary": f"Parameter '{rule.param}' is not an on-site parameter", "detail": {"flow": flow.name, "node": rule.node}}
    raw = _rule_value(rule, context)
    if spec.kind == "boolean" and isinstance(raw, str) and raw.strip().lower() not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
        return {"ok": False, "action": rule.action, "summary": f"Value for '{rule.param}' is not valid", "detail": {"flow": flow.name, "node": rule.node, "value": raw}}
    value = base.coerce_param(spec, raw)
    if value is base._BAD_PARAM:
        return {"ok": False, "action": rule.action, "summary": f"Value for '{rule.param}' is not valid", "detail": {"flow": flow.name, "node": rule.node, "value": raw}}
    if spec.kind == "select" and spec.options:
        allowed = {str(item.get("value")) for item in spec.options}
        if str(value) not in allowed:
            return {"ok": False, "action": rule.action, "summary": f"Value for '{rule.param}' is not one of the allowed options", "detail": {"flow": flow.name, "node": rule.node, "value": value}}

    from django.db import transaction
    from apps.vision.models import FlowRecipe

    with transaction.atomic():
        recipe = flow.recipes.select_for_update().filter(is_default=True).first()
        if recipe is None:
            recipe = FlowRecipe.objects.create(flow=flow, name="Runtime overrides", is_default=True)
        overrides = dict(recipe.param_overrides or {})
        node_patch = dict(overrides.get(rule.node) or {})
        node_patch[rule.param] = value
        overrides[rule.node] = node_patch
        recipe.param_overrides = overrides
        recipe.save(update_fields=["param_overrides", "updated_at"])
    return {
        "ok": True, "action": rule.action, "summary": f"{flow.name}.{rule.node}.{rule.param}={value}",
        "detail": {"flow": flow.name, "recipe": recipe.name, "node": rule.node, "param": rule.param, "value": value},
    }


def _context_value(name: str, incoming: dict[str, Any], args: dict[str, Any]) -> Any:
    return incoming[name] if name in incoming else args.get(name)


def _calibration_signal(rule: Rule, incoming: dict[str, Any]) -> dict[str, Any]:
    """把接收規則解析到的標定訊號放進行程內佇列。"""
    from apps.vision import calib_signals

    args = dict(rule.args or {})
    x = _context_value("x", incoming, args)
    y = _context_value("y", incoming, args)
    r = _context_value("r", incoming, args)
    if rule.signal_kind in ("point", "teach") and (x in (None, "") or y in (None, "")):
        return {"ok": False, "action": rule.action, "summary": f"{rule.signal_kind} needs x and y", "detail": {"kind": rule.signal_kind}}
    try:
        if rule.signal_kind == "start":
            calib_signals.clear()
        item = calib_signals.push(rule.signal_kind, x=x, y=y, r=r, source=str(incoming.get("text") or rule.label()))
    except ValueError as exc:
        return {"ok": False, "action": rule.action, "summary": str(exc), "detail": {"kind": rule.signal_kind}}
    return {"ok": True, "action": rule.action, "summary": f"calibration {rule.signal_kind} #{item['seq']}", "detail": item}


def fire(rule: Rule, context: dict[str, Any] | None = None, *, trigger: str = "rule", find_flow=find_flow) -> dict[str, Any]:
    """執行規則的動作。回 `{ok, action, summary, detail}`；例外由呼叫端記進追蹤，不往上丟。

    `find_flow` 可以換掉（輪詢迴圈用有快取的版本，PLC 每 50 ms 觸發也不會每次查資料庫）。
    """
    incoming = dict(context or {})
    context = dict(incoming)
    context.update(rule.args)
    if rule.action == "run_flow":
        flow = find_flow(rule.flow)
        if flow is None:
            raise LookupError(f"Flow '{rule.flow}' does not exist or is disabled")
        from apps.vision.runner import runner

        report = runner.run_sync(flow, trigger=trigger, context=context or None, recipe=rule.recipe or None)
        return {
            "ok": report.status != "failed", "action": rule.action, "summary": f"{flow.name}: {report.status}",
            "detail": {"flow": flow.name, "run_id": report.id, "status": report.status, "outputs": report.outputs, "error": report.error},
            "outputs": report.outputs, "status": report.status, "run_id": report.id,
        }
    if rule.action == "activate_recipe":
        from django.db import transaction

        flow = find_flow(rule.flow)
        if flow is None:
            raise LookupError(f"Flow '{rule.flow}' does not exist or is disabled")
        recipe = flow.recipes.filter(name=rule.recipe).first()
        if recipe is None:
            raise LookupError(f"Recipe '{rule.recipe}' does not exist on flow '{flow.name}'")
        with transaction.atomic():
            flow.recipes.exclude(pk=recipe.pk).update(is_default=False)
            if not recipe.is_default:
                recipe.is_default = True
                recipe.save(update_fields=["is_default", "updated_at"])
        return {"ok": True, "action": rule.action, "summary": f"{flow.name} -> {recipe.name}", "detail": {"flow": flow.name, "recipe": recipe.name}}
    if rule.action == "set_variable":
        from apps.vision import variables

        flow_id = None
        if rule.scope == "flow":
            flow = find_flow(rule.flow)
            if flow is None:
                raise LookupError(f"Flow '{rule.flow}' does not exist or is disabled")
            flow_id = flow.id
        # set_value 支援 {名字} 取觸發帶進來的引數，這樣文字規則抓到的料號可以直接存成變數
        raw = render(rule.set_value, context) if "{" in rule.set_value else rule.set_value
        stored = variables.store.set(variables.scope_for(flow_id, rule.scope), rule.variable, variables.parse_default(raw))
        return {"ok": True, "action": rule.action, "summary": f"{rule.variable}={stored}", "detail": {"scope": rule.scope, "name": rule.variable, "value": stored}}
    if rule.action == "set_param":
        return _set_param(rule, context, find_flow=find_flow)
    if rule.action == "calibration_signal":
        return _calibration_signal(rule, incoming)
    if rule.action in ("lock", "unlock"):
        from apps.accounts.models import EngineLock

        lock = EngineLock.current()
        if rule.action == "lock":
            lock.acquire("integrator", rule.reason or "Locked by a trigger rule", ttl_s=rule.ttl or None)
        else:
            lock.release()
        return {"ok": True, "action": rule.action, "summary": rule.action, "detail": lock.to_dict()}
    raise ValueError(f"Unknown action '{rule.action}'")


__all__ = [
    "ACTIONS", "EDGE_MODES", "MAX_RULES", "Rule", "SCOPES", "SIGNAL_KINDS", "SOURCES", "TEXT_MATCHES", "VALUE_MODES",
    "find_flow", "fire", "from_legacy", "invalidate", "match_text", "match_value", "parse", "render", "rules_of",
    "sanitize", "save_station_rules", "station_rules", "watched_addresses",
]
