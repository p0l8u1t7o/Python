"""
檢測模組介面、參數結構與統一結果格式

每個檢測模組繼承 InspectionModule，宣告：
  - module_id / version / names (繁中、英文) / supported_kinds
  - params：參數結構 (Param 清單)，平台據此產生配方設定畫面並檢查輸入
  - overlay_styles：各類檢測物件的疊圖樣式
並實作 run(ctx, params) -> ModuleResult。

結果以 Finding (檢測物件) 與 Group (物件群組，例如陣列) 表示，幾何與量測值都是一般資料，
介面、報告、資料庫不需要為新模組另外開發。
"""
from dataclasses import dataclass, field
from importlib import metadata

# 模組狀態
STATUS_OK = "ok"                    # 正常完成
STATUS_NO_RESULT = "no_result"      # 無法判定 (影像不適用、可量測目標不足等)，reasons 說明原因
STATUS_ERROR = "error"              # 執行錯誤

ENTRY_POINT_GROUP = "xrayvision.inspections"

# 判定 (模組層級與影像層級共用)
JUDGE_PASS = "pass"
JUDGE_FAIL = "fail"
JUDGE_REVIEW = "review"                        # 需複判
JUDGE_QUALITY = "quality_insufficient"         # 影像品質不足 (僅影像層級)
JUDGE_NOT_JUDGED = "not_judged"                # 未設定判定規格，只提供量測值


@dataclass
class Param:
    """
    檢測模組參數定義。
    type: float / int / bool / enum / model；label 為 {語系: 文字}；unit 為顯示單位 (px、deg、ratio 等)。
    model：深度學習模型參照 "模型代碼@版本" (空字串為不使用)；choices 放適用的任務名稱 (例如 void_segmentation)
    advanced=True 的參數在配方畫面預設收合。
    """
    key: str
    type: str
    default: object
    label: dict
    min: object = None
    max: object = None
    choices: tuple = ()
    unit: str = ""
    advanced: bool = False

    def validate(self, value):
        if self.type == "float":
            value = float(value)
        elif self.type == "int":
            if isinstance(value, float) and not value.is_integer():
                raise ParamError(self.key, "not_integer", value)
            value = int(value)
        elif self.type == "bool":
            if not isinstance(value, bool):
                raise ParamError(self.key, "not_bool", value)
        elif self.type == "enum":
            if value not in self.choices:
                raise ParamError(self.key, "not_in_choices", value)
        elif self.type == "model":
            from .modelpkg import REF_PATTERN
            value = "" if value is None else str(value)
            if value and not REF_PATTERN.match(value):
                raise ParamError(self.key, "invalid_model_ref", value)
            return value
        if self.min is not None and value < self.min:
            raise ParamError(self.key, "below_min", value)
        if self.max is not None and value > self.max:
            raise ParamError(self.key, "above_max", value)
        return value

    def to_dict(self):
        return dict(key=self.key, type=self.type, default=self.default, label=self.label, min=self.min,
                    max=self.max, choices=list(self.choices), unit=self.unit, advanced=self.advanced)


class ParamError(ValueError):
    def __init__(self, key, code, value):
        super().__init__(f"{key}: {code} ({value!r})")
        self.key, self.code, self.value = key, code, value


@dataclass
class Finding:
    """
    檢測物件。geometry 為一組具名幾何，例如：
      {"bump": {"type": "circle", "x":…, "y":…, "r":…}, "pad": {...}, "offset": {"type": "vector", …}}
    measurements 為數值量測；used=False 表示未採用 (reason 為原因代碼)。
    """
    id: int
    category: str
    geometry: dict
    measurements: dict = field(default_factory=dict)
    group: int = 0
    used: bool = True
    reason: str = ""
    flags: dict = field(default_factory=dict)


@dataclass
class Group:
    """檢測物件群組 (例如同一個凸塊陣列)；estimate 為群組層級的估計結果"""
    id: int
    category: str
    bbox: tuple
    size: int
    estimate: dict = None
    grade: str = ""
    measurements: dict = field(default_factory=dict)
    source: str = "auto"               # auto = 模組自動分群；region = 檢測區域「視為一個陣列」
    label: str = ""                    # 顯示名稱 (region 時為區域名稱)


@dataclass
class ModuleResult:
    module_id: str
    module_version: str
    status: str
    params: dict
    findings: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)       # 影像層級結果 (例如晶片偏移)
    metrics: dict = field(default_factory=dict)       # 模組專屬品質指標
    reasons: list = field(default_factory=list)       # 原因代碼 (no_result 或注意事項)
    rejects: dict = field(default_factory=dict)       # 候選物件剔除原因統計
    rejected: list = field(default_factory=list)      # 剔除的候選物件 (位置、原因)
    elapsed_s: float = 0.0
    judgment: str = ""                                # 模組判定 (JUDGE_*)，由平台依配方規格呼叫 judge() 填入
    judgment_reasons: list = field(default_factory=list)


class InspectionModule:
    module_id = ""
    version = "0.0.0"
    names = {}                     # {"zh-TW": …, "en": …}
    supported_kinds = ()
    params = ()                    # Param 清單
    overlay_styles = {}            # {幾何名稱: {"color": (B, G, R), "thickness": int}}
    quality_rules = ()             # 模組預設品質規則 (quality.QualityRule)，指標鍵為 "<module_id>.<指標>"
    # 重複性與不變性驗證 (validation.py)：以哪個幾何的圓心配對同一物件、比較哪些量測值、影像層級向量結果
    repeat_anchor = ""             # 例如 "bump"
    repeat_keys = ()               # 例如 ("dx_px", "dy_px")
    summary_vector = ""            # summary 中含 dx、dy 的鍵，例如 "die_shift"
    judgment_params = ()           # 判定規格 (Param 清單)，數值由配方的 modules[].judgment 設定
    # 外部模組的顯示文字 (選用)：{"zh-TW": {鍵: 文字}, "en": {...}}，併入平台語系 (平台既有的鍵不覆蓋)。
    # 至少提供 module.<代碼>、各品質指標 metric.<代碼>.<指標>、原因代碼 reason.<代碼>
    translations = None
    # 報告與檢閱畫面的物件排行表 (選用)：dict(category=物件類別, sort=排序量測值, columns=(量測值, ...), limit=筆數)
    finding_table = None
    # 是否支援檢測區域的「視為一個陣列」(ctx.region_group)；不支援的模組忽略該設定
    supports_region_arrays = False

    def run(self, ctx, params):
        raise NotImplementedError

    def warm(self, ctx, params):
        """
        預先準備 (選用)：互動分析在使用者切換影像前，於背景先做與參數無關、耗時的步驟並快取，
        之後 run() 直接沿用。不得改變 run() 的結果。預設不做事。
        """

    def judge(self, result, spec, pixel_size_um=None):
        """
        依判定規格判定模組結果；回傳 (level, reasons)。
        level：pass / fail / review / not_judged (未設定規格)。預設不判定。
        """
        return JUDGE_NOT_JUDGED, []

    @classmethod
    def resolve_judgment(cls, overrides=None):
        pm = {p.key: p for p in cls.judgment_params}
        out = {k: p.default for k, p in pm.items()}
        for k, v in (overrides or {}).items():
            if k not in pm:
                raise ParamError(k, "unknown_param", v)
            out[k] = None if v is None else pm[k].validate(v)
        return out

    @classmethod
    def param_map(cls):
        return {p.key: p for p in cls.params}

    @classmethod
    def resolve_params(cls, overrides=None):
        """合併預設值與配方參數並檢查；未知參數視為錯誤 (避免配方打錯字卻靜默使用預設值)"""
        pm = cls.param_map()
        out = {k: p.default for k, p in pm.items()}
        for k, v in (overrides or {}).items():
            if k not in pm:
                raise ParamError(k, "unknown_param", v)
            out[k] = pm[k].validate(v)
        return out

    @classmethod
    def describe(cls):
        return dict(module_id=cls.module_id, version=cls.version, names=cls.names,
                    supported_kinds=list(cls.supported_kinds), params=[p.to_dict() for p in cls.params],
                    judgment_params=[p.to_dict() for p in cls.judgment_params],
                    quality_rules=[r.to_dict() for r in cls.quality_rules],
                    overlay_styles={k: dict(v, color="#{2:02x}{1:02x}{0:02x}".format(*v["color"]))
                                    for k, v in cls.overlay_styles.items() if "color" in v},
                    summary_vector=cls.summary_vector, supports_region_arrays=bool(cls.supports_region_arrays),
                    finding_table=dict(cls.finding_table, columns=list(cls.finding_table["columns"]))
                    if cls.finding_table else None)


# ---------------------------------------------------------------------------
# 模組註冊
# ---------------------------------------------------------------------------
_REGISTRY = {}


def register(cls):
    """註冊檢測模組 (可當裝飾器使用)"""
    if not cls.module_id:
        raise ValueError("module_id is required")
    _REGISTRY[cls.module_id] = cls
    return cls


def _discover():
    # 內建模組
    from .. import inspections  # noqa: F401  (匯入時自行註冊)
    # 外部安裝的模組套件：以 entry point 宣告
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        eps = metadata.entry_points().get(ENTRY_POINT_GROUP, [])
    for ep in eps:
        register(ep.load())


def available():
    _discover()
    return dict(_REGISTRY)


def get(module_id):
    mods = available()
    if module_id not in mods:
        raise KeyError(module_id)
    return mods[module_id]
