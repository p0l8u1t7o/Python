"""
檢測模組驗證狀態 (規劃書 PLAN-002 第 3.6 節)

以「模組代碼＋主版.次版」為單位記錄驗證狀態；紀錄只新增，同一單位最新一筆為目前狀態。
未驗證的模組仍可使用，但判定最多為需複判，紀錄與報告註記「模組未驗證」。
"""
from ..core import plugin
from ..core.pipeline import module_series
from ..store.db import now

VALIDATED = "validated"
REVOKED = "revoked"


class ModuleValidationError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def current(db):
    """{(模組代碼, 主版.次版): 最新紀錄}"""
    rows = db.all("SELECT * FROM module_validations ORDER BY id")
    return {(r["module_id"], r["series"]): r for r in rows}


def validated_set(db):
    """已驗證的 (模組代碼, 主版.次版) 清單 (可 JSON 序列化，傳給分析子行程)"""
    return sorted([list(k) for k, r in current(db).items() if r["status"] == VALIDATED])


def overview(db):
    """已安裝模組與其目前版本的驗證狀態、歷程"""
    cur = current(db)
    out = []
    for mid, cls in sorted(plugin.available().items()):
        series = module_series(cls.version)
        row = cur.get((mid, series))
        history = db.all("SELECT status, note, report_name, actor, created_at FROM module_validations "
                         "WHERE module_id = ? AND series = ? ORDER BY id DESC", (mid, series))
        out.append(dict(module_id=mid, version=cls.version, series=series, names=cls.names,
                        status=row["status"] if row and row["status"] == VALIDATED else "unvalidated",
                        approved_by=row["actor"] if row else None, approved_at=row["created_at"] if row else None,
                        note=row["note"] if row else "", history=history))
    return out


def set_status(db, module_id, status, actor, note="", report_name=""):
    """核准 (validated) 或撤銷 (revoked) 目前安裝版本的驗證狀態"""
    if status not in (VALIDATED, REVOKED):
        raise ModuleValidationError("invalid_validation_status", status)
    try:
        cls = plugin.get(module_id)
    except KeyError:
        raise ModuleValidationError("unknown_module", module_id)
    series = module_series(cls.version)
    note = (note or "").strip()
    if status == VALIDATED and not note:
        raise ModuleValidationError("validation_note_required", module_id)
    row = current(db).get((module_id, series))
    if (row and row["status"] == status) or (not row and status == REVOKED):
        raise ModuleValidationError("validation_status_unchanged", module_id)
    db.insert("module_validations", module_id=module_id, series=series, status=status, note=note,
              report_name=report_name or "", actor=actor, created_at=now())
    db.audit(actor, "module.validate" if status == VALIDATED else "module.revoke", "module", module_id,
             series=series, note=note, report_name=report_name or "")
    return next(m for m in overview(db) if m["module_id"] == module_id)
