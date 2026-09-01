"""教育訓練平台 API。

公開讀取（知識庫、課程、題目）不需登入；作答、完成章節、提交專案、評分需要登入。
登入用 Django session：前端先 GET /api/training/csrf 取得 cookie，POST 時帶 X-CSRFToken。
"""

from datetime import datetime
from typing import Optional

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth
from ninja.utils import check_csrf

from .models import (
    Article,
    Course,
    IdentificationGuide,
    KnowledgeCard,
    Lesson,
    LessonProgress,
    Profile,
    Project,
    ProjectSubmission,
    QuizAttempt,
    QuizQuestion,
)

router = Router(tags=["training"])


def profile_of(user) -> Profile:
    """取得（必要時建立）使用者的 Profile。"""
    prof, _ = Profile.objects.get_or_create(user=user)
    return prof


def require_csrf(request) -> None:
    """給沒有 auth=django_auth 的寫入端點用。

    django-ninja 只在 SessionAuth 裡做 CSRF 檢查，所以 login／register／作答這類
    不帶 auth 的 POST 預設是 csrf_exempt 的，得自己補上。
    """
    if check_csrf(request) is not None:
        raise HttpError(403, "CSRF 驗證失敗，請重新整理頁面")


# ---------------------------------------------------------------- 知識庫


class CardOut(Schema):
    id: int
    code: str
    category: str
    name: str
    name_en: str
    function: str
    install_location: str
    tip: str
    photo: Optional[str] = None
    photo_credit: str
    photo_source_url: str
    component_ids: list[int]

    @staticmethod
    def resolve_photo(obj: KnowledgeCard):
        return obj.photo.url if obj.photo else None

    @staticmethod
    def resolve_component_ids(obj: KnowledgeCard):
        return [c.id for c in obj.components.all()]


@router.get("/cards", response=list[CardOut])
def list_cards(request, category: str = "", q: str = "", component_id: int = 0):
    """元件知識卡。可依分類、關鍵字，或「對應到某個實機元件」篩選。"""
    qs = KnowledgeCard.objects.prefetch_related("components")
    if category:
        qs = qs.filter(category=category)
    if component_id:
        qs = qs.filter(components__id=component_id)
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(name_en__icontains=q)
            | Q(code__icontains=q)
            | Q(function__icontains=q)
            | Q(install_location__icontains=q)
            | Q(tip__icontains=q)
        )
    return qs.distinct()


@router.get("/cards/{code}", response=CardOut)
def get_card(request, code: str):
    return get_object_or_404(KnowledgeCard, code=code)


class IdentOut(Schema):
    id: int
    look: str
    tell: str
    key_fields: str
    common_mistake: str
    candidates: list[CardOut]


@router.get("/identification", response=list[IdentOut])
def list_identification(request):
    """來料辨識流程。"""
    return IdentificationGuide.objects.prefetch_related("candidates")


class ArticleListOut(Schema):
    id: int
    slug: str
    title: str
    category: str
    tags: list
    summary: str
    updated_at: datetime
    author: Optional[str] = None

    @staticmethod
    def resolve_author(obj: Article):
        return obj.author.get_username() if obj.author else None


class ArticleOut(ArticleListOut):
    content_markdown: str


@router.get("/articles", response=list[ArticleListOut])
def list_articles(request, category: str = "", tag: str = "", q: str = ""):
    """技術文檔。q 同時搜標題、內文與標籤，錯誤碼直接當關鍵字搜。"""
    qs = Article.objects.filter(published=True).select_related("author")
    if category:
        qs = qs.filter(category=category)
    if tag:
        qs = qs.filter(tags__icontains=tag)
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(summary__icontains=q)
            | Q(content_markdown__icontains=q) | Q(tags__icontains=q)
        )
    return qs


@router.get("/articles/{slug}", response=ArticleOut)
def get_article(request, slug: str):
    return get_object_or_404(Article.objects.select_related("author"), slug=slug, published=True)


# ---------------------------------------------------------------- 課程


class LessonListOut(Schema):
    id: int
    slug: str
    title: str
    summary: str
    card_category: str
    equipment_slug: Optional[str] = None
    card_count: int
    completed: bool = False

    @staticmethod
    def resolve_equipment_slug(obj: Lesson):
        return obj.equipment.slug if obj.equipment else None

    @staticmethod
    def resolve_card_count(obj: Lesson):
        return obj.cards.count()


class LessonOut(LessonListOut):
    content_markdown: str
    video_url: str
    cards: list[CardOut]


class CourseOut(Schema):
    id: int
    slug: str
    title: str
    description: str
    level: int
    lessons: list[LessonListOut]
    locked: bool = False
    completed_count: int = 0


def _annotate_progress(courses, user) -> list[Course]:
    """標記每章是否完成，並依 level 逐級解鎖：前一級全部完成才解鎖下一級。"""
    done: set[int] = set()
    if user.is_authenticated:
        done = set(
            LessonProgress.objects.filter(user=user).values_list("lesson_id", flat=True)
        )
    by_level: dict[int, list[Course]] = {}
    for c in courses:
        c.completed_count = sum(1 for ls in c.lessons.all() if ls.id in done)
        for ls in c.lessons.all():
            ls.completed = ls.id in done
        by_level.setdefault(c.level, []).append(c)

    unlocked = True
    for level in sorted(by_level):
        for c in by_level[level]:
            c.locked = not unlocked
        # 這一級全部章節都完成，才解鎖下一級
        unlocked = unlocked and all(
            ls.id in done for c in by_level[level] for ls in c.lessons.all()
        )
    return courses


@router.get("/courses", response=list[CourseOut])
def list_courses(request):
    """學習地圖：課程依 level 分級，附完成度與解鎖狀態。"""
    courses = list(Course.objects.filter(published=True).prefetch_related("lessons"))
    return _annotate_progress(courses, request.user)


@router.get("/courses/{slug}", response=CourseOut)
def get_course(request, slug: str):
    course = get_object_or_404(
        Course.objects.prefetch_related("lessons"), slug=slug, published=True
    )
    return _annotate_progress([course], request.user)[0]


@router.get("/courses/{course_slug}/lessons/{lesson_slug}", response=LessonOut)
def get_lesson(request, course_slug: str, lesson_slug: str):
    lesson = get_object_or_404(
        Lesson.objects.select_related("course", "equipment").prefetch_related("cards__components"),
        course__slug=course_slug,
        slug=lesson_slug,
    )
    lesson.completed = (
        request.user.is_authenticated
        and LessonProgress.objects.filter(user=request.user, lesson=lesson).exists()
    )
    return lesson


class OkOut(Schema):
    ok: bool
    detail: str = ""


@router.post("/lessons/{lesson_id}/complete", response=OkOut, auth=django_auth)
def complete_lesson(request, lesson_id: int):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    _, created = LessonProgress.objects.get_or_create(user=request.user, lesson=lesson)
    return {"ok": True, "detail": "已標記完成" if created else "先前已完成"}


@router.delete("/lessons/{lesson_id}/complete", response=OkOut, auth=django_auth)
def uncomplete_lesson(request, lesson_id: int):
    LessonProgress.objects.filter(user=request.user, lesson_id=lesson_id).delete()
    return {"ok": True, "detail": "已取消完成標記"}


# ---------------------------------------------------------------- 測驗


class QuestionOut(Schema):
    """不含正解：答案由後端判定，避免直接從前端看到。"""

    id: int
    prompt: str
    options: list
    answered_index: Optional[int] = None
    answered_correct: Optional[bool] = None


@router.get("/quiz", response=list[QuestionOut])
def list_quiz(request, course: str = ""):
    qs = QuizQuestion.objects.all()
    qs = qs.filter(course__slug=course) if course else qs.filter(course__isnull=True)
    questions = list(qs)
    if request.user.is_authenticated:
        latest: dict[int, QuizAttempt] = {}
        for a in QuizAttempt.objects.filter(
            user=request.user, question__in=questions
        ).order_by("created_at"):
            latest[a.question_id] = a
        for q in questions:
            if a := latest.get(q.id):
                q.answered_index, q.answered_correct = a.chosen_index, a.correct
    return questions


class AnswerIn(Schema):
    chosen_index: int


class AnswerOut(Schema):
    correct: bool
    answer_index: int
    explanation: str


@router.post("/quiz/{question_id}/answer", response=AnswerOut)
def answer_quiz(request, question_id: int, payload: AnswerIn):
    """判題。已登入才會留下作答紀錄；未登入也能練習。"""
    require_csrf(request)
    q = get_object_or_404(QuizQuestion, id=question_id)
    correct = payload.chosen_index == q.answer_index
    if request.user.is_authenticated:
        QuizAttempt.objects.create(
            user=request.user, question=q, chosen_index=payload.chosen_index, correct=correct
        )
    return {"correct": correct, "answer_index": q.answer_index, "explanation": q.explanation}


# ---------------------------------------------------------------- Mini Project


class ProjectListOut(Schema):
    id: int
    slug: str
    title: str
    level: int
    summary: str
    course_slug: Optional[str] = None
    my_status: Optional[str] = None

    @staticmethod
    def resolve_course_slug(obj: Project):
        return obj.course.slug if obj.course else None


class ProjectOut(ProjectListOut):
    spec_markdown: str
    acceptance_markdown: str


class SubmissionOut(Schema):
    id: int
    project_slug: str
    project_title: str
    student: str
    repo_url: str
    note: str
    status: str
    mentor_feedback: str
    score: Optional[int] = None
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None

    @staticmethod
    def resolve_project_slug(obj: ProjectSubmission):
        return obj.project.slug

    @staticmethod
    def resolve_project_title(obj: ProjectSubmission):
        return obj.project.title

    @staticmethod
    def resolve_student(obj: ProjectSubmission):
        return obj.student.get_username()


def _my_status(projects, user):
    if not user.is_authenticated:
        return projects
    mine = {
        s.project_id: s.status
        for s in ProjectSubmission.objects.filter(student=user).order_by("submitted_at")
    }
    for p in projects:
        p.my_status = mine.get(p.id)
    return projects


@router.get("/projects", response=list[ProjectListOut])
def list_projects(request):
    projects = list(Project.objects.filter(published=True).select_related("course"))
    return _my_status(projects, request.user)


@router.get("/projects/{slug}", response=ProjectOut)
def get_project(request, slug: str):
    p = get_object_or_404(Project.objects.select_related("course"), slug=slug, published=True)
    return _my_status([p], request.user)[0]


class SubmitIn(Schema):
    repo_url: str = ""
    note: str = ""


@router.post("/projects/{slug}/submit", response=SubmissionOut, auth=django_auth)
def submit_project(request, slug: str, payload: SubmitIn):
    project = get_object_or_404(Project, slug=slug, published=True)
    return ProjectSubmission.objects.create(
        project=project, student=request.user, repo_url=payload.repo_url, note=payload.note
    )


@router.get("/submissions", response=list[SubmissionOut], auth=django_auth)
def list_submissions(request, project: str = "", status: str = ""):
    """學員只看得到自己的；導師與管理員看得到全部。"""
    qs = ProjectSubmission.objects.select_related("project", "student")
    if not profile_of(request.user).is_mentor:
        qs = qs.filter(student=request.user)
    if project:
        qs = qs.filter(project__slug=project)
    if status:
        qs = qs.filter(status=status)
    return qs


class ReviewIn(Schema):
    status: str
    mentor_feedback: str = ""
    score: Optional[int] = None


@router.post("/submissions/{submission_id}/review", response=SubmissionOut, auth=django_auth)
def review_submission(request, submission_id: int, payload: ReviewIn):
    if not profile_of(request.user).is_mentor:
        raise HttpError(403, "只有導師或管理員可以評分")
    sub = get_object_or_404(ProjectSubmission, id=submission_id)
    sub.status = payload.status
    sub.mentor_feedback = payload.mentor_feedback
    sub.score = payload.score
    sub.mentor = request.user
    sub.reviewed_at = timezone.now()
    sub.save()
    return sub


# ---------------------------------------------------------------- 身分


class MeOut(Schema):
    authenticated: bool
    username: str = ""
    display_name: str = ""
    role: str = ""
    department: str = ""
    lessons_done: int = 0
    lessons_total: int = 0
    quiz_correct: int = 0
    quiz_answered: int = 0


def _me(user) -> dict:
    if not user.is_authenticated:
        return {"authenticated": False, "lessons_total": Lesson.objects.count()}
    prof = profile_of(user)
    latest: dict[int, bool] = {}
    for a in QuizAttempt.objects.filter(user=user).order_by("created_at"):
        latest[a.question_id] = a.correct
    return {
        "authenticated": True,
        "username": user.get_username(),
        "display_name": prof.display_name or user.get_username(),
        "role": prof.role,
        "department": prof.department,
        "lessons_done": LessonProgress.objects.filter(user=user).count(),
        "lessons_total": Lesson.objects.count(),
        "quiz_correct": sum(1 for v in latest.values() if v),
        "quiz_answered": len(latest),
    }


@router.get("/me", response=MeOut)
def me(request):
    return _me(request.user)


class CsrfOut(Schema):
    csrf_token: str


@router.get("/csrf", response=CsrfOut)
def csrf(request):
    """發 csrftoken：同時設 cookie（由 CsrfViewMiddleware 寫入）並回傳字串供前端帶在 X-CSRFToken。"""
    return {"csrf_token": get_token(request)}


class LoginIn(Schema):
    username: str
    password: str


@router.post("/auth/login", response=MeOut)
def auth_login(request, payload: LoginIn):
    require_csrf(request)
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None:
        raise HttpError(401, "帳號或密碼不正確")
    login(request, user)
    profile_of(user)
    return _me(user)


@router.post("/auth/logout", response=OkOut)
def auth_logout(request):
    require_csrf(request)
    logout(request)
    return {"ok": True}


class RegisterIn(Schema):
    username: str
    password: str
    display_name: str = ""
    department: str = ""


@router.post("/auth/register", response=MeOut)
def auth_register(request, payload: RegisterIn):
    """自助註冊，一律開為學員；導師與管理員由 Django admin 調整角色。"""
    require_csrf(request)
    if User.objects.filter(username=payload.username).exists():
        raise HttpError(400, "帳號已存在")
    if len(payload.password) < 8:
        raise HttpError(400, "密碼至少 8 個字元")
    user = User.objects.create_user(username=payload.username, password=payload.password)
    Profile.objects.create(
        user=user, display_name=payload.display_name, department=payload.department
    )
    login(request, user)
    return _me(user)

