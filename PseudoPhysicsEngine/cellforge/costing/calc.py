"""成本計算：公式、捨入階段與缺價處理都明示在輸出中，金額一律以十進位計算。

- 設備對應（equipment）依 cell.yaml 的模組實例展開：增刪設備時採購數量與成本自動同步。
- 組件有自己的單價時子件不另計價；單價待報價時展開子件計價；兩者同時出現即為重複計價。
- 同一採購項合併成一列採購數量，保留每個來源。
- 缺價（單價 null）、缺匯率或單位不符的列不計入已知成本，另列缺價清單與覆蓋率，不可當成 0。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

from cellforge.schema.costing import KIND_LABELS, LABOR_LABELS, Costing, CostItem
from cellforge.schema.models import Cell

FORMULAS = {
    "material": "材料成本 = Σ(數量 × 單價 × 匯率)；每列小計捨入到 line_decimals",
    "labor": "人工成本 = Σ(工時 × 費率 × 匯率)；每列小計捨入到 line_decimals",
    "equipment": "設備成本 = 採購件、加工件、模組與耗材的已知小計總和",
    "development": "專案開發成本 = 人工成本 + 服務類採購項小計",
    "overhead": "管理費 = 管理費率 × (設備成本 + 專案開發成本)；捨入到 total_decimals",
    "contingency": "預備費 = 預備費率 × (設備成本 + 專案開發成本 + 管理費)；捨入到 total_decimals",
    "cost": "成本合計 = 設備成本 + 專案開發成本 + 管理費 + 預備費；捨入到 total_decimals",
    "budget_tax": "預算稅額 = 稅率 × 成本合計；捨入到 total_decimals",
    "margin": "售價 = 成本合計 ÷ (1 − 毛利率)；捨入到 total_decimals",
    "markup": "售價 = 成本合計 × (1 + 加價率)；捨入到 total_decimals",
    "quote_tax": "報價稅額 = 稅率 × 售價；捨入到 total_decimals",
    "range": "上下限 = 各列 金額 × (1 ∓ 幅度) 的加總，不是統計信賴區間",
}


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


@dataclass
class _Demand:
    item: str
    quantity: Decimal
    source: dict[str, Any]
    unit: str | None = None


@dataclass
class _Context:
    costing: Costing
    issues: list[dict[str, str]] = field(default_factory=list)

    def issue(self, severity: str, code: str, message: str) -> None:
        self.issues.append({"severity": severity, "code": code, "message": message})


def _rounder(costing: Costing):
    mode = ROUND_HALF_UP if costing.policy.rounding.mode == "half_up" else ROUND_HALF_EVEN

    def rounded(value: Decimal, decimals: int) -> Decimal:
        return value.quantize(Decimal(1).scaleb(-decimals), rounding=mode)

    return rounded


def _modules(cell: Cell):
    for machine in cell.machines:
        yield from machine.modules


def _tool_part(instance) -> str | None:
    tool = instance.params.get("tool")
    return str(tool.get("part")).replace("\\", "/") if isinstance(tool, dict) else None


def _matches(rule, instance) -> bool:
    match = rule.match
    checks = [
        match.part is None or (instance.part or "").replace("\\", "/") == match.part,
        match.vendor is None or instance.vendor == match.vendor,
        match.module is None or instance.id == match.module,
        match.tool is None or _tool_part(instance) == match.tool.replace("\\", "/"),
    ]
    return all(checks)


def _demands(context: _Context, cell: Cell) -> list[_Demand]:
    costing = context.costing
    demands: list[_Demand] = []
    seen: dict[tuple[str, str], str] = {}
    module_ids = {instance.id for instance in _modules(cell)}

    def add(demand: _Demand, key_modules: list[str], label: str) -> None:
        for module_id in key_modules:
            key = (demand.item, module_id)
            if key in seen:
                context.issue(
                    "error",
                    "DUPLICATE",
                    f"重複計價：採購項 {demand.item} 對模組 {module_id} 同時由 "
                    f"{seen[key]} 與 {label} 計入，只計一次",
                )
                return
        for module_id in key_modules:
            seen[(demand.item, module_id)] = label
        demands.append(demand)

    for rule in costing.equipment:
        matched = [instance for instance in _modules(cell) if _matches(rule, instance)]
        if rule.match.module and rule.match.module not in module_ids:
            context.issue(
                "error",
                "UNKNOWN_MODULE",
                f"設備對應 {rule.id} 引用不存在的模組：{rule.match.module}",
            )
        if not matched:
            context.issue(
                "warning", "NO_EQUIPMENT", f"設備對應 {rule.id} 沒有對到任何模組實例，數量為 0"
            )
        for instance in matched:
            for entry in rule.items:
                add(
                    _Demand(
                        entry.item,
                        entry.quantity,
                        {"type": "equipment", "id": rule.id, "module": instance.id},
                    ),
                    [instance.id],
                    f"設備對應 {rule.id}",
                )
    for line in costing.bom:
        unknown = sorted(set(line.for_modules) - module_ids)
        if unknown:
            context.issue(
                "warning",
                "UNKNOWN_MODULE",
                f"BOM 列 {line.id} 標示的所屬模組不存在：{'、'.join(unknown)}",
            )
        add(
            _Demand(
                line.item,
                line.quantity,
                {"type": "bom", "id": line.id, "modules": list(line.for_modules)},
                line.unit,
            ),
            list(line.for_modules),
            f"BOM 列 {line.id}",
        )
    return demands


def _explode(context: _Context, demands: list[_Demand]) -> list[_Demand]:
    """Priced assemblies stay whole; unpriced assemblies are costed through their components."""
    items = {item.id: item for item in context.costing.items}
    result: list[_Demand] = []

    def visit(demand: _Demand, path: tuple[str, ...]) -> None:
        item = items[demand.item]
        if item.components and item.price.amount is None:
            for component in item.components:
                visit(
                    _Demand(
                        component.item,
                        demand.quantity * component.quantity,
                        {**demand.source, "via": [*path, item.id]},
                    ),
                    (*path, item.id),
                )
            return
        result.append(demand)

    for demand in demands:
        visit(demand, ())
    # 組件已有單價、又單獨計入其子件（同一設備）即為重複計價。
    priced = defaultdict(set)
    for demand in result:
        item = items[demand.item]
        if item.components and item.price.amount is not None:
            for module in _source_modules(demand.source):
                for component in item.components:
                    priced[(component.item, module)].add(item.id)
    for demand in result:
        for module in _source_modules(demand.source):
            parents = priced.get((demand.item, module))
            if parents:
                context.issue(
                    "error",
                    "ASSEMBLY_DOUBLE_COUNT",
                    f"組件 {'、'.join(sorted(parents))} 已含單價，子件 {demand.item} 又對模組 "
                    f"{module} 單獨計入：組件總價與子件成本不可同時計入",
                )
    return result


def _source_modules(source: dict[str, Any]) -> list[str]:
    if "module" in source:
        return [source["module"]]
    return list(source.get("modules", []))


def _exchange(context: _Context, currency: str) -> tuple[Decimal | None, dict | None]:
    target = context.costing.policy.currency
    if currency == target:
        return Decimal("1"), None
    for rate in context.costing.exchange_rates:
        if rate.from_currency == currency and rate.to_currency == target:
            return rate.rate, {
                "from": currency,
                "to": target,
                "rate": _text(rate.rate),
                "date": rate.rate_date.isoformat(),
                "source": rate.source,
            }
    return None, None


def _purchase_lines(
    context: _Context, demands: list[_Demand], as_of: date, rounded
) -> list[dict[str, Any]]:
    items: dict[str, CostItem] = {item.id: item for item in context.costing.items}
    decimals = context.costing.policy.rounding.line_decimals
    grouped: dict[str, list[_Demand]] = defaultdict(list)
    for demand in demands:
        grouped[demand.item].append(demand)
    lines = []
    for item_id in [item.id for item in context.costing.items if item.id in grouped]:
        item = items[item_id]
        group = grouped[item_id]
        quantity = sum((demand.quantity for demand in group), Decimal("0"))
        missing = None
        units = sorted(
            {demand.unit for demand in group if demand.unit and demand.unit != item.unit}
        )
        if units:
            missing = f"單位不符（{'、'.join(units)} ≠ {item.unit}）"
            context.issue("error", "UNIT_MISMATCH", f"採購項 {item_id} 的數量單位不符：{missing}")
        rate, exchange = _exchange(context, item.price.currency)
        price = item.price.amount
        if missing is None and price is None:
            missing = "待報價"
        if missing is None and rate is None:
            missing = f"缺匯率 {item.price.currency}→{context.costing.policy.currency}"
            context.issue("error", "NO_EXCHANGE_RATE", f"採購項 {item_id}：{missing}")
        if item.price.valid_until and item.price.valid_until < as_of:
            context.issue(
                "warning",
                "QUOTE_EXPIRED",
                f"採購項 {item_id} 的報價已於 {item.price.valid_until.isoformat()} 過期",
            )
        amount = low = high = None
        if missing is None and quantity != 0:
            amount = rounded(quantity * price * rate, decimals)
            spread = item.price.range_pct or Decimal("0")
            low = rounded(amount * (1 - spread), decimals)
            high = rounded(amount * (1 + spread), decimals)
        elif missing is None:
            amount = low = high = Decimal("0")
        lines.append(
            {
                "item": item_id,
                "name": item.name,
                "kind": item.kind,
                "kind_label": KIND_LABELS[item.kind],
                "subsystem": item.subsystem,
                "model": item.model,
                "spec": item.spec,
                "supplier": item.supplier,
                "part_no": item.part_no,
                "unit": item.unit,
                "quantity": _text(quantity),
                "unit_price": _text(price),
                "price_currency": item.price.currency,
                "exchange": exchange,
                "exchange_rate": _text(rate),
                "amount": _text(amount),
                "amount_low": _text(low),
                "amount_high": _text(high),
                "missing": missing,
                "price_source": item.price.source,
                "quote_date": item.price.quote_date.isoformat() if item.price.quote_date else None,
                "valid_until": (
                    item.price.valid_until.isoformat() if item.price.valid_until else None
                ),
                "trust": item.price.trust,
                "grade": item.price.grade,
                "range_pct": _text(item.price.range_pct),
                "applies_to": item.applies_to,
                "components_not_costed": (
                    [component.item for component in item.components]
                    if item.components and price is not None
                    else []
                ),
                "sources": [
                    {**demand.source, "quantity": _text(demand.quantity)} for demand in group
                ],
            }
        )
    return lines


def _labor_lines(context: _Context, rounded) -> list[dict[str, Any]]:
    rates = {rate.id: rate for rate in context.costing.labor.rates}
    decimals = context.costing.policy.rounding.line_decimals
    lines = []
    for task in context.costing.labor.tasks:
        rate = rates[task.rate]
        exchange, detail = _exchange(context, rate.currency)
        missing = None
        amount = low = high = None
        if exchange is None:
            missing = f"缺匯率 {rate.currency}→{context.costing.policy.currency}"
            context.issue("error", "NO_EXCHANGE_RATE", f"工時 {task.id}：{missing}")
        else:
            amount = rounded(task.quantity * rate.rate * exchange, decimals)
            spread = task.range_pct or Decimal("0")
            low = rounded(amount * (1 - spread), decimals)
            high = rounded(amount * (1 + spread), decimals)
        lines.append(
            {
                "id": task.id,
                "category": task.category,
                "category_label": LABOR_LABELS[task.category],
                "name": task.name,
                "quantity": _text(task.quantity),
                "unit": rate.unit,
                "rate_id": rate.id,
                "rate": _text(rate.rate),
                "rate_currency": rate.currency,
                "exchange": detail,
                "amount": _text(amount),
                "amount_low": _text(low),
                "amount_high": _text(high),
                "grade": task.grade,
                "range_pct": _text(task.range_pct),
                "missing": missing,
                "basis": task.basis or rate.basis,
            }
        )
    return lines


def _sum(values) -> Decimal:
    return sum((Decimal(value) for value in values if value is not None), Decimal("0"))


def compute_costing(costing: Costing, cell: Cell, *, as_of: date | None = None) -> dict[str, Any]:
    """Compute the costing result for one frozen version (all amounts as exact decimal strings)."""

    context = _Context(costing)
    as_of = costing.as_of or as_of or date.today()
    rounded = _rounder(costing)
    policy = costing.policy
    total_decimals = policy.rounding.total_decimals
    demands = _explode(context, _demands(context, cell))
    purchase = _purchase_lines(context, demands, as_of, rounded)
    labor = _labor_lines(context, rounded)

    equipment_lines = [line for line in purchase if line["kind"] != "service"]
    service_lines = [line for line in purchase if line["kind"] == "service"]
    by_subsystem = []
    for subsystem in dict.fromkeys(line["subsystem"] for line in purchase):
        rows = [line for line in purchase if line["subsystem"] == subsystem]
        by_subsystem.append(
            {
                "subsystem": subsystem,
                "known": _text(_sum(line["amount"] for line in rows)),
                "low": _text(_sum(line["amount_low"] for line in rows)),
                "high": _text(_sum(line["amount_high"] for line in rows)),
                "missing": sum(1 for line in rows if line["missing"]),
            }
        )

    totals: dict[str, dict[str, Decimal | None]] = {}
    for suffix, name in (("", "value"), ("_low", "low"), ("_high", "high")):
        equipment = _sum(line[f"amount{suffix}"] for line in equipment_lines)
        labor_total = _sum(line[f"amount{suffix}"] for line in labor)
        services = _sum(line[f"amount{suffix}"] for line in service_lines)
        development = labor_total + services
        base = equipment + development
        overhead = rounded(policy.overhead_rate * base, total_decimals)
        contingency = rounded(policy.contingency_rate * (base + overhead), total_decimals)
        cost = rounded(base + overhead + contingency, total_decimals)
        budget_tax = rounded(policy.tax_rate * cost, total_decimals)
        values = {
            "equipment": equipment,
            "labor": labor_total,
            "services": services,
            "development": development,
            "overhead": overhead,
            "contingency": contingency,
            "cost": cost,
            "budget_tax": budget_tax,
            "budget_with_tax": cost + budget_tax,
        }
        if policy.pricing is not None:
            if policy.pricing.method == "margin":
                price = rounded(cost / (1 - policy.pricing.rate), total_decimals)
            else:
                price = rounded(cost * (1 + policy.pricing.rate), total_decimals)
            quote_tax = rounded(policy.tax_rate * price, total_decimals)
            values.update(
                {"price": price, "quote_tax": quote_tax, "quote_with_tax": price + quote_tax}
            )
        for key, value in values.items():
            totals.setdefault(key, {})[name] = value
    missing = [
        {
            "type": "purchase",
            "id": line["item"],
            "name": line["name"],
            "quantity": line["quantity"],
            "unit": line["unit"],
            "reason": line["missing"],
            "sources": line["sources"],
        }
        for line in purchase
        if line["missing"]
    ] + [
        {
            "type": "labor",
            "id": line["id"],
            "name": line["name"],
            "quantity": line["quantity"],
            "unit": line["unit"],
            "reason": line["missing"],
        }
        for line in labor
        if line["missing"]
    ]
    total_lines = len(purchase) + len(labor)
    priced = total_lines - len(missing)
    return {
        "currency": policy.currency,
        "as_of": as_of.isoformat(),
        "complete": not missing,
        "policy": {
            "overhead_rate": _text(policy.overhead_rate),
            "contingency_rate": _text(policy.contingency_rate),
            "tax_rate": _text(policy.tax_rate),
            "rounding": policy.rounding.model_dump(mode="json"),
            "pricing": policy.pricing.model_dump(mode="json") if policy.pricing else None,
        },
        "formulas": FORMULAS,
        "exchange_rates": [
            {
                "from": rate.from_currency,
                "to": rate.to_currency,
                "rate": _text(rate.rate),
                "date": rate.rate_date.isoformat(),
                "source": rate.source,
            }
            for rate in costing.exchange_rates
        ],
        "purchase_lines": purchase,
        "labor_lines": labor,
        "by_subsystem": by_subsystem,
        "totals": {
            key: {name: _text(value) for name, value in values.items()}
            for key, values in totals.items()
        },
        "coverage": {
            "priced_lines": priced,
            "total_lines": total_lines,
            "ratio": _text(
                (Decimal(priced) / Decimal(total_lines)).quantize(Decimal("0.0001"))
                if total_lines
                else Decimal("1")
            ),
        },
        "missing": missing,
        "issues": context.issues,
        "notes": list(costing.notes),
    }
