"""後台：導師用來上架課程、撰寫技術文檔與批改專案。"""

from django.contrib import admin

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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "role", "department", "created_at")
    list_filter = ("role", "department")
    search_fields = ("user__username", "display_name")


@admin.register(KnowledgeCard)
class KnowledgeCardAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "name_en", "category", "order")
    list_filter = ("category",)
    search_fields = ("code", "name", "name_en", "function", "tip")
    filter_horizontal = ("components",)


@admin.register(IdentificationGuide)
class IdentificationGuideAdmin(admin.ModelAdmin):
    list_display = ("look", "order")
    filter_horizontal = ("candidates",)


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "author", "published", "updated_at")
    list_filter = ("category", "published")
    search_fields = ("title", "summary", "content_markdown")
    prepopulated_fields = {"slug": ("title",)}


class LessonInline(admin.StackedInline):
    model = Lesson
    extra = 0
    filter_horizontal = ("cards",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "order", "published")
    list_filter = ("level", "published")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "card_category", "order")
    list_filter = ("course", "card_category")
    filter_horizontal = ("cards",)


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "course", "answer_index", "order")
    list_filter = ("course",)
    search_fields = ("prompt", "explanation")


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "question", "chosen_index", "correct", "created_at")
    list_filter = ("correct",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "course", "published", "order")
    list_filter = ("level", "published")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ProjectSubmission)
class ProjectSubmissionAdmin(admin.ModelAdmin):
    list_display = ("project", "student", "status", "score", "submitted_at", "reviewed_at")
    list_filter = ("status", "project")
    search_fields = ("student__username", "note", "mentor_feedback")


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "completed_at")
    list_filter = ("lesson__course",)
