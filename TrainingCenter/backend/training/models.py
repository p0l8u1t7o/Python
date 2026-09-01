"""教育訓練平台（LMS）資料模型。

分四塊：
  * 身分：Profile（角色）
  * 知識庫：KnowledgeCard（元件知識卡）／IdentificationGuide（來料辨識）／Article（技術文檔）
  * 課程：Course → Lesson → LessonProgress，關卡依 level 逐級解鎖
  * 評測：QuizQuestion／QuizAttempt、Project／ProjectSubmission

KnowledgeCard 與 catalog.Component 的分工：
  Component 是「某台設備的某顆料」（綁 Equipment/Module，有 3D 座標與 mesh）；
  KnowledgeCard 是「這類元件的通用知識」（跨設備、有辨識重點與作業提醒）。
  兩者用 M2M 互相連結，讓 3D 頁點到元件時能帶出知識卡。
"""

from django.conf import settings
from django.db import models

from catalog.models import Component, Equipment


class Profile(models.Model):
    """使用者角色與所屬單位。PRD 的 users 表以 Django User + Profile 實作。"""

    class Role(models.TextChoices):
        STUDENT = "student", "學員"
        MENTOR = "mentor", "導師"
        ADMIN = "admin", "管理員"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    display_name = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True, help_text="部門／課別")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.display_name or self.user.username}（{self.get_role_display()}）"

    @property
    def is_mentor(self) -> bool:
        return self.role in (self.Role.MENTOR, self.Role.ADMIN)


# --------------------------------------------------------------------------
# 知識庫
# --------------------------------------------------------------------------


class KnowledgeCard(models.Model):
    """元件知識卡：一張卡講一個元件的功用、位置與現場重點。

    code 沿用教材的料號規則（系統代碼 + 流水號，如 MEC-01），現場文件可直接對照。
    """

    class Category(models.TextChoices):
        MECH = "mech", "機構"
        PNE = "pne", "氣路"
        ELEC = "elec", "電控"
        SOFT = "soft", "軟體"
        CNV = "cnv", "輸送帶模組"
        ARM = "arm", "機械手臂"
        AOI = "aoi", "AOI 光學"
        FCS = "fcs", "氫燃料電池"

    code = models.CharField(max_length=20, unique=True, help_text="如 MEC-01")
    category = models.CharField(max_length=10, choices=Category.choices)
    name = models.CharField(max_length=100)
    name_en = models.CharField(max_length=150, blank=True)
    function = models.TextField(help_text="這個元件在做什麼")
    install_location = models.CharField(max_length=300, help_text="裝在哪裡")
    tip = models.TextField(blank=True, help_text="現場重點／最常見的錯誤")
    photo = models.ImageField(upload_to="knowledge/", blank=True, null=True)
    photo_credit = models.CharField(max_length=300, blank=True)
    photo_source_url = models.URLField(blank=True)
    photo_query = models.CharField(max_length=200, blank=True, help_text="抓圖用英文關鍵字")
    # 對應到實機 BOM 上的元件（可多台設備）
    components = models.ManyToManyField(
        Component, blank=True, related_name="knowledge_cards"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class IdentificationGuide(models.Model):
    """來料辨識：看到這個外觀，怎麼確定它是什麼、要核對哪些欄位、最常收錯什麼。"""

    look = models.CharField(max_length=300, help_text="外觀描述（學員從這裡找起）")
    tell = models.TextField(help_text="怎麼確定是哪一種")
    key_fields = models.TextField(help_text="一定要核對的欄位")
    common_mistake = models.TextField(help_text="最常見的收錯")
    candidates = models.ManyToManyField(
        KnowledgeCard, blank=True, related_name="identification_guides"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.look[:40]


class Article(models.Model):
    """技術文檔：導師自行撰寫的 Markdown 文章，支援多重 Tag 與錯誤碼搜尋。"""

    class Category(models.TextChoices):
        HARDWARE = "hardware", "硬體與通訊"
        VISION = "vision", "視覺與 AI"
        MOTION = "motion", "運動控制"
        SOFTWARE = "software", "軟體與系統"
        TROUBLESHOOTING = "troubleshooting", "除錯與 Log 分析"

    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices)
    tags = models.JSONField(default=list, blank=True, help_text='如 ["LabVIEW", "EtherCAT"]')
    summary = models.CharField(max_length=300, blank=True)
    content_markdown = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title


# --------------------------------------------------------------------------
# 課程與學習地圖
# --------------------------------------------------------------------------


class Course(models.Model):
    """課程。level 同時是學習地圖的關卡層級：要修完前一級才會解鎖下一級。"""

    LEVELS = {1: "觀念與全貌", 2: "模組與工具", 3: "機種專章與實戰"}

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    level = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["level", "order", "id"]

    def __str__(self) -> str:
        return f"L{self.level} {self.title}"


class Lesson(models.Model):
    """課程章節。content_markdown 是教材本文，cards 帶出本章涵蓋的元件卡。"""

    course = models.ForeignKey(Course, related_name="lessons", on_delete=models.CASCADE)
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=300, blank=True)
    content_markdown = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    # 本章對應的元件卡分類；前端據此把整個分類的卡片列出來
    card_category = models.CharField(max_length=10, blank=True)
    cards = models.ManyToManyField(KnowledgeCard, blank=True, related_name="lessons")
    # 可選：連到某台實機設備的 3D 頁
    equipment = models.ForeignKey(
        Equipment, null=True, blank=True, on_delete=models.SET_NULL, related_name="lessons"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("course", "slug")]

    def __str__(self) -> str:
        return f"{self.course.title} / {self.title}"


class LessonProgress(models.Model):
    """學員完成某章節的紀錄。有紀錄即視為完成。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress"
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "lesson")]

    def __str__(self) -> str:
        return f"{self.user} 完成 {self.lesson}"


# --------------------------------------------------------------------------
# 測驗
# --------------------------------------------------------------------------


class QuizQuestion(models.Model):
    """單選題。course 為空表示通用題庫（隨堂測驗）。"""

    course = models.ForeignKey(
        Course, null=True, blank=True, on_delete=models.CASCADE, related_name="questions"
    )
    prompt = models.TextField()
    options = models.JSONField(default=list, help_text="選項字串陣列")
    answer_index = models.PositiveSmallIntegerField(help_text="正解在 options 中的索引，從 0 起算")
    explanation = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.prompt[:40]


class QuizAttempt(models.Model):
    """作答紀錄。同一題可重複作答，統計時取最新一筆。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quiz_attempts"
    )
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name="attempts")
    chosen_index = models.PositiveSmallIntegerField()
    correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# --------------------------------------------------------------------------
# Mini Project
# --------------------------------------------------------------------------


class Project(models.Model):
    """實戰演練題目：規格、輸入輸出定義與驗收標準。"""

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=200)
    level = models.PositiveSmallIntegerField(default=1)
    summary = models.CharField(max_length=300, blank=True)
    spec_markdown = models.TextField(blank=True, help_text="需求規格與輸入輸出定義")
    acceptance_markdown = models.TextField(blank=True, help_text="驗收標準")
    course = models.ForeignKey(
        Course, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["level", "order", "id"]

    def __str__(self) -> str:
        return self.title


class ProjectSubmission(models.Model):
    """學員提交與導師評分。"""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        UNDER_REVIEW = "under_review", "審核中"
        PASSED = "passed", "通過"
        REJECTED = "rejected", "退回"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions"
    )
    repo_url = models.URLField(blank=True)
    upload = models.FileField(upload_to="submissions/", blank=True, null=True)
    note = models.TextField(blank=True, help_text="學員自述：做法與已知問題")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_submissions",
    )
    mentor_feedback = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.student} → {self.project}（{self.get_status_display()}）"
