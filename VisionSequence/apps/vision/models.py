"""資料模型。

Flow：操作者畫的那張圖（整份 JSON 存一個欄位，編輯器整份存、引擎整份讀）。
FlowRun：一次執行的**摘要**記錄。影像不進資料庫；執行中的中間影像在記憶體快取
（apps.vision.images），前端用 ref 取。高速產線可用 VISION_PERSIST_RUNS=0 關掉。
ImageSource：影像來源（資料夾、單檔、USB 相機、合成、外掛）。
Asset：上傳的範本影像、ONNX 模型等檔案。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q


class Flow(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    graph = models.JSONField(default=dict)
    #: 擁有者；null = 共用（示範流程、被刪除使用者留下的流程），管理員才能改。
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="flows")
    is_enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    #: 連續模式的間隔（毫秒；0 = 盡快）。
    continuous_interval_ms = models.PositiveIntegerField(default=0)
    #: 這條流程跑多久算逾時（秒；0＝不限）。語意刻意與 VisionMaster 一致：**跑完當前節點才停**，
    #: 不硬砍執行中的工具，所以量到的時間會略大於設定值。整體保險仍是 RUN_TIMEOUT_S。
    timeout_s = models.PositiveIntegerField(default=0)
    #: 任何節點判 NG 就不再往下跑（省掉後面的工站時間）；預設關閉，行為與以前相同。
    stop_on_ng = models.BooleanField(default=False)
    #: 現場教導完成（參數卡頁確認）；False 時 run 仍可執行，只在 RunReport 加 warnings。
    commissioned = models.BooleanField(default=False)
    #: 影像封存策略（見 apps/vision/archive.py）；空 dict＝用 .env 的出貨預設。
    archive_policy = models.JSONField(default=dict, blank=True)
    #: 現場看板要顯示什麼（見 apps/vision/board.py）；空 dict＝全部具名輸出＋最後一張影像。
    board = models.JSONField(default=dict, blank=True)
    #: 結果要回送給誰、送什麼（見 apps/vision/reporting.py）；空清單＝不回送。
    comm = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FlowVariable(models.Model):
    """流程／站台變數的落地副本——記憶體是正本（apps/vision/variables.py），這裡只為了重開機不丟。flow=NULL 是站台範圍。"""

    flow = models.ForeignKey("Flow", null=True, blank=True, on_delete=models.CASCADE, related_name="variables")
    name = models.CharField(max_length=64)
    value = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["flow", "name"], name="uniq_flow_variable")]


class FlowVersion(models.Model):
    """流程每一次存檔的快照。

    `Flow.version` 本來只是一個累加的整數——良品基準寫著「流程 v40」，可是 v40 的圖早就不存在，
    既不能比較也回不去。這張表把每次存檔的 graph 留下來，並允許把某一版標記為「發行版」
    （只是標記，不擋執行；量產跑的仍是流程當前的圖）。
    """

    flow = models.ForeignKey("Flow", on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    graph = models.JSONField(default=dict)
    saved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    saved_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True, default="")
    #: 工程師簽核過的版本；淘汰時永遠保留。
    is_released = models.BooleanField(default=False)

    class Meta:
        ordering = ["-version"]
        unique_together = [("flow", "version")]
        indexes = [models.Index(fields=["flow", "-version"])]

    def __str__(self) -> str:
        return f"{self.flow_id} v{self.version}"


class FlowRecipe(models.Model):
    """配方：同一流程的一組參數覆寫（多料號換線用）。param_overrides = {node_id: {param: value}}。"""

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="recipes")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    param_overrides = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("flow", "name")]


RUN_STATUSES = ("ok", "ng", "failed", "cancelled")


class FlowRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="runs")
    flow_version = models.PositiveIntegerField()
    status = models.CharField(max_length=12)
    trigger = models.CharField(max_length=20, default="manual")  # manual | api | continuous | tcp | preview
    station_id = models.CharField(max_length=40, default="ST01")
    recipe = models.CharField(max_length=80, blank=True, default="")
    duration_ms = models.FloatField(default=0)
    #: 各節點摘要：{node_id: {status, duration_ms, message}}
    nodes = models.JSONField(default=dict)
    #: output 工具收集的具名輸出。
    outputs = models.JSONField(default=dict)
    #: 已封存的影像 {ref: 相對於封存根目錄的路徑}；空＝這次沒有封存。
    images = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["flow", "-started_at"]), models.Index(fields=["station_id", "-started_at"])]


class FlowRunHourly(models.Model):
    """每小時一列的良率彙總，**永久保留**。

    明細（`FlowRun`）本來只留每流程最近 2000 筆——產線一秒一次就是 33 分鐘的歷史，品保隔天
    要查早班紀錄時資料早就被自己刪掉了。改成明細留天數、彙總永久保留：一年 8760 列而已，
    趨勢圖與報表查它，重開機或清明細都不會讓良率曲線消失。
    """

    flow = models.ForeignKey("Flow", on_delete=models.CASCADE, related_name="hourly")
    #: 該小時的起點（UTC，分秒為 0）。
    hour = models.DateTimeField(db_index=True)
    station_id = models.CharField(max_length=40, default="ST01")
    recipe = models.CharField(max_length=80, blank=True, default="")
    ok = models.PositiveIntegerField(default=0)
    ng = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    total_ms = models.FloatField(default=0.0)
    max_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-hour"]
        unique_together = [("flow", "hour", "station_id", "recipe")]
        indexes = [models.Index(fields=["flow", "-hour"])]

    @property
    def total(self) -> int:
        return self.ok + self.ng + self.failed


class MeasurementLog(models.Model):
    """具名數值輸出的輕量時間序列（WP-14 SPC）：每次 run 的每個數值輸出一列，與明細 `FlowRun` 分開保留。

    明細 30 天就淘汰、還有筆數上限，SPC 要看的是「孔徑最近三個月在往上漂」——所以另存一張只有
    (flow, run, name, value, ts, station) 的表，保留天數獨立（`MEASUREMENT_DAYS`，0＝永久）。寫入走
    持久化執行緒的同一批 bulk_create，不碰引擎熱路徑。
    """

    flow = models.ForeignKey("Flow", on_delete=models.CASCADE, related_name="measurements")
    run_id = models.UUIDField()
    name = models.CharField(max_length=80)
    value = models.FloatField()
    ts = models.DateTimeField()
    station_id = models.CharField(max_length=40, default="ST01")

    class Meta:
        indexes = [models.Index(fields=["flow", "name", "ts"], name="vision_meas_flow_name_ts")]

    def __str__(self) -> str:
        return f"{self.flow_id} {self.hour:%Y-%m-%d %H} {self.total}"



class ImageSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20)
    #: 使用者自訂群組（自由文字；"" = 未分組）。前端依群組篩選／分區顯示。
    group = models.CharField(max_length=60, blank=True, default="")
    #: 依 kind 不同：folder {path, loop, sort}；file {path}；capture {client, channel, mode, ...}；
    #: synthetic {width, height, pattern}；plugin {class, ...}
    config = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FlowTemplate(models.Model):
    """自訂流程範本：圖裡的 image_source.source_id 存成 {SOURCE} 佔位符，載入時換成目標來源。"""

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=40, default="custom")
    graph = models.JSONField(default=dict)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="flow_templates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class ResourceGroup(models.Model):
    """使用者自訂的資源群組（影像來源庫／資產庫共用）：kind=source|asset。

    項目上的 group 仍是字串（鬆耦合）；這張表讓「空群組」可以存在、支援改名／刪除管理。
    列表 API 會把項目上出現但表裡沒有的群組自動補列（舊資料回填）。"""

    kind = models.CharField(max_length=10)  # source | asset
    name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("kind", "name")]


class Asset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20)  # image | model | file | dataset
    #: 使用者自訂群組（自由文字；"" = 未分組）。
    group = models.CharField(max_length=60, blank=True, default="")
    path = models.CharField(max_length=500)
    size = models.PositiveBigIntegerField(default=0)
    #: 影像資產的寬高，模型資產的輸入形狀等。
    meta = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# 平台內深度學習教導（apps/vision/dl）
# ---------------------------------------------------------------------------
class DlProject(models.Model):
    """一個教導專案：一種模型（trainer_kind）＋類別清單＋樣本集。"""

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    trainer_kind = models.CharField(max_length=40)
    #: 類別名稱清單（label_mode=classes）。
    classes = models.JSONField(default=list)
    #: 訓練超參數（依 trainer 的 params 宣告；空 = 用預設）。
    params = models.JSONField(default=dict)
    #: 最近一次成功訓練的資產與指標。
    last_asset_id = models.CharField(max_length=40, blank=True, default="")
    last_metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class DlSample(models.Model):
    """一張樣本影像；檔案存 ASSET_DIR/dl/<project_id>/<id>.png。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(DlProject, on_delete=models.CASCADE, related_name="samples")
    #: "" = 未標記；classes 模式存類別名。
    label = models.CharField(max_length=80, blank=True, default="")
    #: shapes 模式：[{"label": 類別名, "kind": "polygon"|"bbox", "points": [[x,y],…]}]，座標 0~1 正規化。
    shapes = models.JSONField(default=list, blank=True)
    #: 標記來源：human | auto（自動標記後尚未人工確認）。
    labeled_by = models.CharField(max_length=10, blank=True, default="")
    #: 自動標記的信心分數。
    score = models.FloatField(default=0)
    #: 解碼後像素的 SHA256（同專案內去重；舊資料為空字串，不參與比對）。
    sha256 = models.CharField(max_length=64, blank=True, default="")
    #: 資料集分割：train｜val｜test；"" = 未指定（匯出／訓練時隨機分）。
    split = models.CharField(max_length=8, blank=True, default="")
    path = models.CharField(max_length=500)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["project", "label"]), models.Index(fields=["project", "sha256"])]


class DlDatasetVersion(models.Model):
    """凍結一份資料集版本：把當下樣本與標記匯出成 zip 存進資產庫（kind=dataset），可下載回溯。"""

    project = models.ForeignKey(DlProject, on_delete=models.CASCADE, related_name="versions")
    name = models.CharField(max_length=120)
    note = models.TextField(blank=True, default="")
    #: 凍結當下的統計：total／labeled／per_class／split 數量／classes。
    stats = models.JSONField(default=dict)
    #: 對應 Asset（zip 檔）的 UUID hex；資產被刪時版本仍留統計。
    asset_id = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DlSettings(models.Model):
    """單列（id=1）：推論 providers 與訓練裝置偏好（devices.py 讀進記憶體快取）。"""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    providers = models.JSONField(default=list)
    train_device = models.CharField(max_length=20, default="cpu")
    updated_at = models.DateTimeField(auto_now=True)


# ---------------------------------------------------------------------------
# AI 助手記憶（apps/vision/agent/memory.py）
# ---------------------------------------------------------------------------
class AgentSession(models.Model):
    """一次 AI 助手生成：影像（檔案在 ASSET_DIR/agent/<id>/）、ROI、需求、特徵向量、產出的流程與結果；可評分、可還原、可當先驗。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_sessions")
    task = models.CharField(max_length=20, default="generate")
    prompt = models.TextField(blank=True, default="")
    intent = models.CharField(max_length=40, blank=True, default="")
    provider = models.CharField(max_length=40, blank=True, default="")
    mode = models.CharField(max_length=20, default="single")
    turns = models.PositiveIntegerField(default=0)
    #: [{path, name, width, height}]
    images = models.JSONField(default=list, blank=True)
    regions = models.JSONField(default=list, blank=True)
    answers = models.JSONField(default=list, blank=True)
    labels = models.JSONField(default=list, blank=True)
    #: {"vector": [...], "image_count": n}
    features = models.JSONField(default=dict, blank=True)
    graph = models.JSONField(default=dict)
    rationale = models.TextField(blank=True, default="")
    candidates = models.JSONField(default=list, blank=True)
    statuses = models.JSONField(default=list, blank=True)
    #: 標記全部命中＝True；沒有標記＝None。
    success = models.BooleanField(null=True, blank=True)
    #: 使用者評分：1 讚、-1 倒讚、0 未評。
    rating = models.SmallIntegerField(default=0)
    note = models.TextField(blank=True, default="")
    flow = models.ForeignKey(Flow, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AgentSession {self.pk} ({self.intent})"


class AgentSkill(models.Model):
    """站點／個人對 AI 代理技能的補充（markdown，附在內建技能之後）：key 是技能鍵（platform／design／agentic／工具型別）。"""

    key = models.CharField(max_length=60)
    scope = models.CharField(max_length=10, default="user")  # site | user
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="agent_skills")
    markdown = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("key", "scope", "owner")]
        ordering = ["key", "scope"]


class AssistantMemory(models.Model):
    """全域 AI 助手的長期記憶（每位使用者自己的）：kind=fact 是使用者要它記住的一句話（「記住：…」）；
    kind=qa 是問過的問答（text＝問題、answer＝回答、context＝當時的頁面），可評分，評過好的在相似問題時當範例。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_memories")
    kind = models.CharField(max_length=8)  # fact | qa
    text = models.TextField()
    answer = models.TextField(blank=True, default="")
    context = models.JSONField(default=dict, blank=True)
    rating = models.SmallIntegerField(default=0)  # -1 / 0 / 1
    hits = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "kind"])]


# ---------------------------------------------------------------------------
# 批次測試（apps/vision/batch）
# ---------------------------------------------------------------------------
BATCH_RUN_STATUSES = ("queued", "running", "done", "cancelled", "failed")
BATCH_ORIGINS = ("manual", "draft", "autotune", "ai_tune")


class BatchSet(models.Model):
    """影像集：一組批量測試用的影像（檔案在 ASSET_DIR/batch/<id>/NNN.png）＋每張的期望標記；同一組影像可重複執行比較參數。"""

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="batch_sets")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="batch_sets")
    name = models.CharField(max_length=120)
    #: upload 或 source:<來源名稱>
    source = models.CharField(max_length=120, blank=True, default="")
    #: [{index, name, path, width, height, expected(""|"ok"|"ng"), expect_outputs{}, note}]
    images = models.JSONField(default=list, blank=True)
    image_count = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["flow", "-created_at"])]

    def __str__(self) -> str:
        return f"BatchSet {self.pk} ({self.name})"


class BatchRun(models.Model):
    """一次批次執行：graph 快照＋逐張結果（含各節點純量輸出）＋summary／洞察快取；parent 串起調參前後。

    影像集只是測試資料，`flow` 記錄這次「用哪個流程測」（可以不是影像集建立時的流程）；空＝用影像集的流程。
    """

    batch_set = models.ForeignKey(BatchSet, on_delete=models.CASCADE, related_name="runs")
    #: 這次執行用的流程（跨流程測試時與 batch_set.flow 不同）；流程被刪除時退回影像集的流程。
    flow = models.ForeignKey(Flow, null=True, blank=True, on_delete=models.SET_NULL, related_name="batch_runs")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="batch_runs")
    flow_version = models.PositiveIntegerField(default=0)
    graph = models.JSONField(default=dict)
    recipe_name = models.CharField(max_length=80, blank=True, default="")
    label = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    #: manual | draft | autotune | ai_tune
    origin = models.CharField(max_length=12, default="manual")
    #: queued | running | done | cancelled | failed
    status = models.CharField(max_length=12, default="queued")
    progress_done = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    #: {total, ok, ng, failed, avg_ms, max_ms, wall_ms, labeled, match, match_rate, confusion}
    summary = models.JSONField(default=dict, blank=True)
    #: [{index, status, duration_ms, outputs, error, error_node, nodes:{id:{status, duration_ms, message, branch, outputs}}}]
    items = models.JSONField(default=list, blank=True)
    insights = models.JSONField(default=dict, blank=True)
    #: autotune／ai_tune 的說明（change_text、rationale、evals…）
    meta = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["batch_set", "-created_at"])]

    @property
    def target_flow(self) -> Flow:
        """這次執行用的流程（flow 為空＝影像集的流程）。"""
        return self.flow or self.batch_set.flow

    def __str__(self) -> str:
        return f"BatchRun {self.pk} ({self.status})"


class ScriptApproval(models.Model):
    """Python 腳本核准：管理員儲存流程時登記程式碼的 sha256，引擎只執行清單內的腳本（apps/vision/scripts.py）。"""

    code_hash = models.CharField(max_length=64, unique=True)
    code = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_scripts")
    flow = models.ForeignKey(Flow, null=True, blank=True, on_delete=models.SET_NULL, related_name="script_approvals")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ScriptApproval {self.code_hash[:8]}"


class RetentionSettings(models.Model):
    """單列（id=1）：資料保存時限與維護視窗（apps/vision/retention.py 讀進記憶體快取）。

    沒有這一列時用 `.env`／出廠值；前端「設定」頁改的是這一列，改完立刻生效（不必重開伺服器）。
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    #: 0 = 永久保留
    run_days = models.PositiveIntegerField(default=365)
    audit_days = models.PositiveIntegerField(default=365)
    measurement_days = models.PositiveIntegerField(default=365)
    archive_days = models.PositiveIntegerField(default=90)
    archive_max_gb = models.FloatField(default=20.0)
    file_output_days = models.PositiveIntegerField(default=90)
    file_output_max_gb = models.FloatField(default=20.0)
    #: 備份 zip 與還原前資料庫副本各保留幾份
    backup_keep = models.PositiveIntegerField(default=10)
    #: 維護視窗開始的整點（當地時間）：備份整理與 SQLite 空間回收只在這一小時做
    window_hour = models.PositiveSmallIntegerField(default=3)
    vacuum = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    last_sweep_at = models.DateTimeField(null=True, blank=True)
    last_deep_at = models.DateTimeField(null=True, blank=True)
    last_result = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "RetentionSettings"


class AssistantChat(models.Model):
    """全域 AI 助手的一次對話（每位使用者自己的）：標題由第一句話取，訊息是前端 ChatMessage 陣列。

    以前只有一條對話存在瀏覽器（換電腦就不見）；這裡讓使用者開新對話、回到過去的對話、刪掉不要的。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_chats")
    title = models.CharField(max_length=120, blank=True, default="")
    messages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        #: 同一秒存的兩條要有穩定順序（淘汰最舊的時才不會挑錯）
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return f"AssistantChat {self.pk} {self.title[:20]}"


class Dashboard(models.Model):
    """站台層級的運行介面版面（K1a）：跨流程、多 widget，與每流程的 `Flow.board` 是兩層。

    版面 JSON 的形狀與逐型別驗證在 `apps/vision/dashboard.py`（`validate` 嚴格給存檔、`effective` 寬鬆給檢視）。
    `is_default` 站台最多一筆：存檔時把其他的清掉，資料庫再用條件唯一約束擋住並發。
    """

    name = models.CharField(max_length=200)
    layout = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    #: 只是建立者（顯示用）；版面屬於站台不屬於個人
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="dashboards")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="uniq_default_dashboard")]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if self.is_default:
            with transaction.atomic():
                type(self).objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)
