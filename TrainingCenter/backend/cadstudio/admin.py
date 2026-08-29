from django.contrib import admin

from .models import CadJob


@admin.register(CadJob)
class CadJobAdmin(admin.ModelAdmin):
    list_display = ("name", "mode", "status", "created_at")
    list_filter = ("mode", "status")
    readonly_fields = ("id", "created_at", "log", "error")
