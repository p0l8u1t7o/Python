"""成本資料（costing.yaml）：採購項型錄、設備對應、固定 BOM 列、工時、匯率與計算政策。

所有金額、數量與比率以十進位（Decimal）保存；YAML 中的小數先轉成字串再轉十進位，
避免二進位浮點誤差。缺價以 ``amount: null`` 表示「待報價」，不可當成 0。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .base import ForgeModel

ItemKind = Literal["purchased", "fabricated", "consumable", "module", "service"]
LaborCategory = Literal[
    "mechanical",
    "electrical",
    "software",
    "assembly",
    "wiring",
    "commissioning",
    "validation",
    "documentation",
    "poc",
    "management",
    "other",
]
LABOR_LABELS = {
    "mechanical": "機構",
    "electrical": "電控",
    "software": "軟體",
    "assembly": "裝配",
    "wiring": "配線",
    "commissioning": "調試",
    "validation": "驗證",
    "documentation": "文件與訓練",
    "poc": "POC",
    "management": "專案管理",
    "other": "其他",
}
KIND_LABELS = {
    "purchased": "採購件",
    "fabricated": "加工件",
    "consumable": "耗材",
    "module": "模組",
    "service": "服務",
}


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(float(value)))
    return Decimal(str(value))


class DecimalModel(ForgeModel):
    @field_validator("*", mode="before")
    @classmethod
    def _decimal_inputs(cls, value: Any, info) -> Any:
        annotation = cls.model_fields[info.field_name].annotation
        if isinstance(value, float) and "Decimal" in str(annotation):
            return to_decimal(value)
        return value


class Price(DecimalModel):
    """單價；amount 為 null 表示待報價。"""

    amount: Decimal | None = None
    currency: str = "TWD"
    source: str | None = None
    quote_date: date | None = None
    valid_until: date | None = None
    trust: Literal["quoted", "catalog", "estimate", "placeholder"] = "estimate"
    # 估價等級與 ±幅度（上下限為逐列幅度加總，不是統計信賴區間）
    grade: str | None = None
    range_pct: Decimal | None = None


class ComponentRef(DecimalModel):
    item: str
    quantity: Decimal


class CostItem(DecimalModel):
    """採購項型錄：同一料號只列一次，由設備對應與 BOM 列引用。"""

    id: str
    kind: ItemKind
    subsystem: str
    name: str
    unit: str
    price: Price = Field(default_factory=Price)
    spec: str = ""
    model: str = ""
    supplier: str | None = None
    part_no: str | None = None
    rationale: str = ""
    alternative: str = ""
    # 適用的機種、配方或設計版本說明
    applies_to: str | None = None
    # 組件：有自己的單價時子件不另計價；單價待報價時展開子件計價。
    components: list[ComponentRef] = Field(default_factory=list)


class ItemQuantity(DecimalModel):
    item: str
    quantity: Decimal = Decimal("1")


class EquipmentMatch(ForgeModel):
    """選出 cell.yaml 的模組實例；多個條件須同時成立。"""

    part: str | None = None
    vendor: str | None = None
    module: str | None = None
    tool: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> EquipmentMatch:
        if not any((self.part, self.vendor, self.module, self.tool)):
            raise ValueError("設備對應至少要指定 part、vendor、module 或 tool 其中一項")
        return self


class EquipmentRule(ForgeModel):
    """每個符合條件的模組實例各計一次 items；增刪設備時採購數量與成本自動同步。"""

    id: str
    match: EquipmentMatch
    items: list[ItemQuantity]


class BomLine(DecimalModel):
    """不隨模組實例增減的固定列（例如控制器、安全元件）；for 標示所屬設備以檢查重複。"""

    id: str
    item: str
    quantity: Decimal
    unit: str | None = None
    for_modules: list[str] = Field(default_factory=list, alias="for")
    note: str = ""


class LaborRate(DecimalModel):
    id: str
    rate: Decimal
    currency: str = "TWD"
    unit: str = "人日"
    basis: str = ""


class LaborTask(DecimalModel):
    id: str
    category: LaborCategory
    name: str
    quantity: Decimal
    rate: str
    basis: str = ""
    grade: str | None = None
    range_pct: Decimal | None = None


class Labor(ForgeModel):
    rates: list[LaborRate] = Field(default_factory=list)
    tasks: list[LaborTask] = Field(default_factory=list)


class ExchangeRate(DecimalModel):
    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    rate: Decimal
    rate_date: date = Field(alias="date")
    source: str


class Rounding(ForgeModel):
    """捨入階段：明細小計到 line_decimals；預備費、稅額與報價到 total_decimals。"""

    line_decimals: int = 2
    total_decimals: int = 0
    mode: Literal["half_up", "half_even"] = "half_up"


class Pricing(DecimalModel):
    """銷售報價：margin 為毛利率（售價 = 成本 ÷ (1 − 毛利率)），markup 為加價率
    （售價 = 成本 × (1 + 加價率)），兩者擇一、不可混用。"""

    method: Literal["margin", "markup"]
    rate: Decimal
    basis: str = ""

    @model_validator(mode="after")
    def rate_range(self) -> Pricing:
        if self.method == "margin" and not Decimal("0") <= self.rate < Decimal("1"):
            raise ValueError("毛利率必須介於 0 與 1 之間（不含 1）")
        if self.rate < 0:
            raise ValueError("加價率不可為負值")
        return self


class CostPolicy(DecimalModel):
    currency: str = "TWD"
    # 管理費與預備費的基底皆為「設備成本＋專案開發成本」；預備費另含管理費。
    overhead_rate: Decimal = Decimal("0")
    contingency_rate: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    rounding: Rounding = Field(default_factory=Rounding)
    pricing: Pricing | None = None


class Costing(ForgeModel):
    version: Literal[1] = 1
    title: str = ""
    as_of: date | None = None
    policy: CostPolicy = Field(default_factory=CostPolicy)
    exchange_rates: list[ExchangeRate] = Field(default_factory=list)
    items: list[CostItem] = Field(default_factory=list)
    equipment: list[EquipmentRule] = Field(default_factory=list)
    bom: list[BomLine] = Field(default_factory=list)
    labor: Labor = Field(default_factory=Labor)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_valid(self) -> Costing:
        for kind, ids in (
            ("採購項", [item.id for item in self.items]),
            ("設備對應", [rule.id for rule in self.equipment]),
            ("BOM 列", [line.id for line in self.bom]),
            ("工時費率", [rate.id for rate in self.labor.rates]),
            ("工時項目", [task.id for task in self.labor.tasks]),
        ):
            duplicate = sorted({value for value in ids if ids.count(value) > 1})
            if duplicate:
                raise ValueError(f"{kind} id 重複：{', '.join(duplicate)}")
        known = {item.id for item in self.items}
        referenced = {
            *(entry.item for rule in self.equipment for entry in rule.items),
            *(line.item for line in self.bom),
            *(component.item for item in self.items for component in item.components),
        }
        unknown = sorted(referenced - known)
        if unknown:
            raise ValueError(f"成本資料引用不存在的採購項：{', '.join(unknown)}")
        rates = {rate.id for rate in self.labor.rates}
        missing_rates = sorted({task.rate for task in self.labor.tasks} - rates)
        if missing_rates:
            raise ValueError(f"工時項目引用不存在的費率：{', '.join(missing_rates)}")
        _check_component_cycles(self.items)
        return self


def _check_component_cycles(items: list[CostItem]) -> None:
    graph = {item.id: [component.item for component in item.components] for item in items}

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            cycle = " → ".join([*path[path.index(node) :], node])
            raise ValueError(f"採購項組件互相包含成環：{cycle}")
        for child in graph.get(node, []):
            visit(child, [*path, node])

    for node in graph:
        visit(node, [])
