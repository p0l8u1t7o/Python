"""角色權限：管理員勾選工程師與操作員各自能用哪些功能。

以前角色是**寫死的三層**（admin ⊃ engineer ⊃ operator），但每間工廠的分工不一樣——有的
不讓工程師碰深度學習，有的希望操作員能自己跑批次測試。所以功能清單 `FEATURES` 是封閉集合，
每個角色能用哪些存在 `RolePermission`，管理員在使用者頁面勾選。

三條不能動的規則：

- **管理員永遠是全開的**，而且不能被勾掉。權限畫面本身、帳號與系統設定都只有管理員能碰，
  否則工程師可以把自己升成管理員，這個機制就沒有意義了。
- **預設值＝原本的三層權限**，升級後的行為與升級前完全一樣，勾選是加值不是強制設定。
- **伺服器端才算數**：前端只用它決定側欄顯示什麼，每個會改東西的端點都要自己過
  `security.require_feature()`。

功能清單刻意對齊「使用者看得到的功能區塊」，不是端點：勾選畫面要能讓工廠的人看懂。
「看流程與統計」不在清單裡——登入了就看得到，關掉它整套軟體就沒用了，列出來只會讓人誤按。

**不做行程層快取**：`RolePermission` 最多兩列，查一次幾十微秒，而權限查詢一定發生在已經
要打資料庫的請求裡；每個請求的結果由 `Principal` 自己記住（見 `security.Principal.can`）。
模組層快取換來的那點速度不值得「改了權限卻要重開才生效」與測試之間互相污染的風險。
"""

from __future__ import annotations

#: 功能鍵 → (預設給 engineer, 預設給 operator)。管理員一律全開，不在這裡列。
FEATURES: dict[str, tuple[bool, bool]] = {
    "flows.run": (True, True),       # 執行一次、試執行、連續模式
    "flows.teach": (True, True),     # 參數卡（現場教導參數）與換線
    "flows.edit": (True, False),     # 建立、修改、刪除流程圖
    "tools.edit": (True, False),     # 工具庫：建立、修改、刪除複合工具（操作員只能用）
    "sources": (True, False),        # 影像來源
    "assets": (True, False),         # 範本影像、模型、資料集
    "batch": (True, False),          # 批次測試
    "golden": (True, False),         # Golden Set 回歸
    "dl": (True, False),             # 深度學習教導
    "agent": (True, False),          # AI 助手產生／修改流程
    "integration": (True, False),    # 外部整合頁：HTTP／TCP 試打、事件、命令追蹤、擷取端
    "connections": (False, False),   # 建立與修改主動輸出的連線（Modbus、上位機 TCP、外掛）
    "audit": (False, False),         # 稽核軌跡
}

#: 這些角色的權限可以調整；admin 不在其中（全開且不可改）。
EDITABLE_ROLES = ("engineer", "operator")


def defaults(role: str) -> frozenset[str]:
    """原本寫死的三層權限，也是每個角色的出廠值。"""
    if role == "admin":
        return frozenset(FEATURES)
    index = 0 if role == "engineer" else 1
    return frozenset(key for key, flags in FEATURES.items() if flags[index])


def clean(features) -> list[str]:
    """只留認得的功能鍵，並照 FEATURES 的順序排好（畫面與稽核才穩定）。"""
    wanted = {str(f) for f in (features or [])}
    return [key for key in FEATURES if key in wanted]


def allowed(role: str) -> frozenset[str]:
    """這個角色現在能用的功能。管理員全開；沒有設定過的角色用出廠值。"""
    if role == "admin":
        return frozenset(FEATURES)
    from apps.accounts.models import RolePermission

    row = RolePermission.objects.filter(role=role).first() if role in EDITABLE_ROLES else None
    return frozenset(clean(row.features)) if row is not None else defaults(role)


def ordered(features) -> list[str]:
    """照 FEATURES 的順序列出（畫面與 API 回應都用同一個順序）。"""
    return clean(features)


def matrix() -> dict[str, list[str]]:
    """給設定畫面：每個可調角色現在勾了哪些。"""
    return {role: ordered(allowed(role)) for role in EDITABLE_ROLES}


def catalogue() -> list[dict[str, object]]:
    """功能清單（含出廠值），前端照這份畫勾選表。"""
    return [
        {"key": key, "default": {"engineer": flags[0], "operator": flags[1]}}
        for key, flags in FEATURES.items()
    ]
