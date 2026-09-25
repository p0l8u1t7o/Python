"""
配方版本管理

- 同一配方代碼 (recipe_id) 可有多個版本；每個版本狀態為 draft (草稿)、released (已發布)、retired (停用)。
- 只有草稿可修改；發布後內容不可變 (資料庫觸發器強制)，「修改」會以該版本內容建立下一版草稿 (revise)。
- 分析只使用已發布的版本；資料夾監看使用該配方代碼的最新已發布版本。
- 每個版本內容以完整 JSON 保存，並鎖定檢測模組版本 (發布時記錄當時的模組版本)。
"""
import json
import re

from ..core import plugin
from ..core.pipeline import Recipe, RecipeError
from ..store.db import now


class RecipeStoreError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def compatible(locked, installed):
    return locked.split(".")[:2] == installed.split(".")[:2]


def _row(r):
    if r is None:
        return None
    r = dict(r)
    r["name"] = json.loads(r.pop("name_json"))
    r["body"] = json.loads(r.pop("body_json"))
    return r


_DIFF_SKIP = {"version", "module_version"}


def _flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _DIFF_SKIP:
                continue
            p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):                     # 空的 dict 與未設定視為相同
                out.update(_flatten(v, p))
            else:
                out[p] = v
    return out


def body_diff(old, new):
    """配方內容差異；模組以 module_id 對應，區域、品質規則等清單整體比較"""
    def norm(b):
        b = dict(b)
        b["modules"] = {m["module_id"]: m for m in b.get("modules", [])}
        return _flatten(b)
    a, b = norm(old), norm(new)
    return [dict(path=k, old=a.get(k), new=b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


class RecipeStore:
    def __init__(self, db):
        self.db = db

    def list(self, include_retired=False):
        """每個配方代碼一列：最新版本與最新已發布版本"""
        rows = self.db.all("SELECT * FROM recipes ORDER BY recipe_id, version")
        out = {}
        for r in map(_row, rows):
            if r["status"] == "retired" and not include_retired:
                continue
            e = out.setdefault(r["recipe_id"], dict(recipe_id=r["recipe_id"], name=r["name"], versions=[],
                                                    latest_released=None))
            e["versions"].append(dict(id=r["id"], version=r["version"], status=r["status"], created_at=r["created_at"],
                                      released_at=r["released_at"]))
            e["name"] = r["name"]
            if r["status"] == "released":
                e["latest_released"] = r["version"]
        return list(out.values())

    def get(self, pk):
        return _row(self.db.one("SELECT * FROM recipes WHERE id = ?", (pk,)))

    def get_version(self, recipe_id, version):
        return _row(self.db.one("SELECT * FROM recipes WHERE recipe_id = ? AND version = ?", (recipe_id, version)))

    def latest_released(self, recipe_id):
        return _row(self.db.one("SELECT * FROM recipes WHERE recipe_id = ? AND status = 'released' "
                                "ORDER BY version DESC LIMIT 1", (recipe_id,)))

    @staticmethod
    def _validate(body):
        try:
            return Recipe.from_dict(body)
        except RecipeError as e:
            raise RecipeStoreError(e.code, e.detail)

    def create_draft(self, body, actor, note=""):
        """新建草稿：版本號為該配方代碼現有最大版本 + 1 (body 內的 version 會被覆寫)"""
        body = dict(body)
        rid = str(body.get("recipe_id", "")).strip()
        if not rid:
            raise RecipeStoreError("invalid_recipe", "recipe_id")
        cur = self.db.one("SELECT MAX(version) AS v FROM recipes WHERE recipe_id = ?", (rid,))["v"] or 0
        body["version"] = cur + 1
        r = self._validate(body)
        pk = self.db.insert("recipes", recipe_id=rid, version=r.version, name_json=json.dumps(r.name, ensure_ascii=False),
                            body_json=json.dumps(r.to_dict(), ensure_ascii=False), status="draft", note=note,
                            created_at=now(), created_by=actor)
        self.db.audit(actor, "recipe.create_draft", "recipe", pk, recipe_id=rid, version=r.version)
        return self.get(pk)

    def update_draft(self, pk, body, actor):
        cur = self.get(pk)
        if cur is None:
            raise RecipeStoreError("recipe_not_found", pk)
        if cur["status"] != "draft":
            raise RecipeStoreError("recipe_not_draft", pk)
        body = dict(body, recipe_id=cur["recipe_id"], version=cur["version"])
        r = self._validate(body)
        self.db.execute("UPDATE recipes SET body_json = ?, name_json = ? WHERE id = ?",
                        (json.dumps(r.to_dict(), ensure_ascii=False), json.dumps(r.name, ensure_ascii=False), pk))
        self.db.audit(actor, "recipe.update_draft", "recipe", pk, recipe_id=cur["recipe_id"], version=cur["version"])
        return self.get(pk)

    def release(self, pk, actor):
        """發布：記錄當時的檢測模組版本並鎖定內容"""
        cur = self.get(pk)
        if cur is None:
            raise RecipeStoreError("recipe_not_found", pk)
        if cur["status"] != "draft":
            raise RecipeStoreError("recipe_not_draft", pk)
        body = cur["body"]
        mods = plugin.available()
        for m in body["modules"]:
            m["module_version"] = mods[m["module_id"]].version
        self._validate(body)
        from . import models as model_store
        try:
            model_store.check_recipe(self.db, body)
        except model_store.ModelError as e:
            raise RecipeStoreError(e.code, e.detail)
        with self.db.transaction() as c:
            c.execute("UPDATE recipes SET body_json = ? WHERE id = ?", (json.dumps(body, ensure_ascii=False), pk))
            c.execute("UPDATE recipes SET status = 'released', released_at = ?, released_by = ? WHERE id = ?",
                      (now(), actor, pk))
        self.db.audit(actor, "recipe.release", "recipe", pk, recipe_id=cur["recipe_id"], version=cur["version"],
                      module_versions={m["module_id"]: m["module_version"] for m in body["modules"]})
        return self.get(pk)

    def retire(self, pk, actor):
        cur = self.get(pk)
        if cur is None:
            raise RecipeStoreError("recipe_not_found", pk)
        self.db.execute("UPDATE recipes SET status = 'retired' WHERE id = ?", (pk,))
        self.db.audit(actor, "recipe.retire", "recipe", pk, recipe_id=cur["recipe_id"], version=cur["version"])
        return self.get(pk)

    def delete_draft(self, pk, actor):
        cur = self.get(pk)
        if cur is None or cur["status"] != "draft":
            raise RecipeStoreError("recipe_not_draft", pk)
        self.db.execute("DELETE FROM recipes WHERE id = ?", (pk,))
        self.db.audit(actor, "recipe.delete_draft", "recipe", pk, recipe_id=cur["recipe_id"], version=cur["version"])

    def revise(self, pk, actor):
        """
        「修改」：已發布／停用的版本以其內容建立下一版草稿；同一配方已有草稿時直接回傳該草稿 (不產生第二份)。
        草稿的 note 記錄來源版本 (from vN)，供差異比對。
        """
        src = self.get(pk)
        if src is None:
            raise RecipeStoreError("recipe_not_found", pk)
        if src["status"] == "draft":
            return src
        cur = _row(self.db.one("SELECT * FROM recipes WHERE recipe_id = ? AND status = 'draft' ORDER BY version DESC "
                               "LIMIT 1", (src["recipe_id"],)))
        if cur is not None:
            return cur
        body = dict(src["body"], modules=[{k: v for k, v in m.items() if k != "module_version"}
                                          for m in src["body"]["modules"]])
        return self.create_draft(body, actor, note=f"from v{src['version']}")

    def base_of(self, row):
        """草稿的比對基準：note 記錄的來源版本，沒有時取較早的最新發布版本"""
        m = re.match(r"from v(\d+)", row.get("note") or "")
        if m:
            base = self.get_version(row["recipe_id"], int(m.group(1)))
            if base is not None:
                return base
        return _row(self.db.one("SELECT * FROM recipes WHERE recipe_id = ? AND version < ? AND status != 'draft' "
                                "ORDER BY version DESC LIMIT 1", (row["recipe_id"], row["version"])))

    def diff(self, pk):
        """與比對基準的差異：[dict(path, old, new)]；path 以點號分隔 (模組以 module_id 表示)"""
        row = self.get(pk)
        if row is None:
            raise RecipeStoreError("recipe_not_found", pk)
        base = self.base_of(row)
        if base is None:
            return dict(base=None, changes=[])
        return dict(base=dict(id=base["id"], version=base["version"], status=base["status"]),
                    changes=body_diff(base["body"], row["body"]))

    def to_recipe(self, row):
        """
        資料庫列 → pipeline.Recipe；檢查鎖定的模組版本與目前安裝的是否相容。
        主版.次版相同才相容 (量測結果可能改變時模組至少提升次版號)；修訂版號不同仍可使用。
        """
        body = dict(row["body"])
        mods = plugin.available()
        for m in body["modules"]:
            want = m.get("module_version")
            if want and m["module_id"] in mods and not compatible(want, mods[m["module_id"]].version):
                raise RecipeStoreError("module_version_mismatch",
                                       f"{m['module_id']} {want} != {mods[m['module_id']].version}")
        body["modules"] = [{k: v for k, v in m.items() if k != "module_version"} for m in body["modules"]]
        return Recipe.from_dict(body)
