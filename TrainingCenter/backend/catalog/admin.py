from django.contrib import admin

from .models import Component, Equipment, Module


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0


class ComponentInline(admin.TabularInline):
    model = Component
    extra = 0
    fields = ("order", "name", "category", "brand", "part_number", "install_location", "photo")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "scene_key")
    inlines = [ModuleInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "equipment", "domain")
    list_filter = ("equipment", "domain")
    inlines = [ComponentInline]


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "category", "brand", "part_number", "photo")
    list_filter = ("module__equipment", "module__domain", "category")
    search_fields = ("name", "function", "brand", "part_number")
