from django.db import models


class Equipment(models.Model):
    """一台設備（機台）。"""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    summary = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    # 3D 模型：若有真實 CAD 轉出的 glb，填入 media 相對路徑；空白則前端用程序化模型
    model_file = models.FileField(upload_to="models/", blank=True, null=True)
    # 前端程序化 3D 場景的識別鍵
    scene_key = models.CharField(max_length=50)
    hero_image = models.ImageField(upload_to="equipment/", blank=True, null=True)
    # 水氣電教育訓練指南：[{title, icon, items: [str]}]
    utility_guide = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.name


class Module(models.Model):
    """設備下的模組，依領域分成機構／電控／軟體。"""

    class Domain(models.TextChoices):
        MECHANICAL = "mechanical", "機構"
        ELECTRICAL = "electrical", "電控"
        SOFTWARE = "software", "軟體"
        UTILITY = "utility", "水氣電"

    equipment = models.ForeignKey(Equipment, related_name="modules", on_delete=models.CASCADE)
    slug = models.SlugField()
    name = models.CharField(max_length=100)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    # 模組示意圖（可為 2D 圖或截圖）
    diagram = models.ImageField(upload_to="modules/", blank=True, null=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("equipment", "slug")]

    def __str__(self) -> str:
        return f"{self.equipment.name} / {self.name}"


class Component(models.Model):
    """單一元件：功用、安裝位置、照片、3D 熱點座標與動畫鍵。"""

    module = models.ForeignKey(Module, related_name="components", on_delete=models.CASCADE)
    slug = models.SlugField()
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, blank=True, help_text="例如：機械手臂部件、輸送帶模組、氣路元件")
    brand = models.CharField(max_length=100, blank=True)
    part_number = models.CharField(max_length=100, blank=True)
    function = models.TextField(help_text="元件的功用")
    install_location = models.CharField(max_length=200, help_text="安裝位置（口語描述）")
    specs = models.JSONField(default=dict, blank=True)
    # 真實照片：由公司自行拍攝上傳；未上傳時前端顯示佔位圖
    photo = models.ImageField(upload_to="components/", blank=True, null=True)
    photo_credit = models.CharField(max_length=300, blank=True)
    # 照片來源頁（如 Wikimedia Commons 檔案頁），供授權追溯
    photo_source_url = models.URLField(blank=True)
    # 自動抓圖用的英文搜尋關鍵字（Wikimedia Commons）
    photo_query = models.CharField(max_length=200, blank=True)
    # 3D 熱點座標（相對於設備模型原點，單位：公尺）
    pos_x = models.FloatField(default=0)
    pos_y = models.FloatField(default=0)
    pos_z = models.FloatField(default=0)
    # 對應程序化 3D 場景中的 mesh 名稱（用於高亮）
    mesh_name = models.CharField(max_length=50, blank=True)
    # 元件 3D CAD（glb）：可由 text_to_cad 指令產生或自行上傳；有值時詳細面板顯示 3D 檢視
    model_file = models.FileField(upload_to="models/components/", blank=True, null=True)
    model_prompt = models.CharField(max_length=300, blank=True, help_text="text-to-CAD 的英文提示詞")
    # 動畫鍵（前端依此播放對應動畫，如 "robot-joint", "cylinder", "belt"）
    animation_key = models.CharField(max_length=50, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("module", "slug")]

    def __str__(self) -> str:
        return self.name
