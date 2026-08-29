from typing import Optional

from django.shortcuts import get_object_or_404
from ninja import NinjaAPI, Schema

from .models import Component, Equipment, Module

api = NinjaAPI(title="TrainingCenter API", version="1.0")

from cadstudio.api import router as cad_router  # noqa: E402

api.add_router("/cad", cad_router)


class ComponentOut(Schema):
    id: int
    slug: str
    name: str
    category: str
    brand: str
    part_number: str
    function: str
    install_location: str
    specs: dict
    photo: Optional[str] = None
    photo_credit: str
    photo_source_url: str
    model_file: Optional[str] = None
    pos: list[float]
    mesh_name: str
    animation_key: str

    @staticmethod
    def resolve_photo(obj: Component):
        return obj.photo.url if obj.photo else None

    @staticmethod
    def resolve_model_file(obj: Component):
        return obj.model_file.url if obj.model_file else None

    @staticmethod
    def resolve_pos(obj: Component):
        return [obj.pos_x, obj.pos_y, obj.pos_z]


class ModuleOut(Schema):
    id: int
    slug: str
    name: str
    domain: str
    description: str
    diagram: Optional[str] = None
    components: list[ComponentOut]

    @staticmethod
    def resolve_diagram(obj: Module):
        return obj.diagram.url if obj.diagram else None


class EquipmentListOut(Schema):
    id: int
    slug: str
    name: str
    summary: str
    scene_key: str
    hero_image: Optional[str] = None
    component_count: int

    @staticmethod
    def resolve_hero_image(obj: Equipment):
        return obj.hero_image.url if obj.hero_image else None

    @staticmethod
    def resolve_component_count(obj: Equipment):
        return Component.objects.filter(module__equipment=obj).count()


class EquipmentOut(EquipmentListOut):
    description: str
    model_file: Optional[str] = None
    utility_guide: list
    modules: list[ModuleOut]

    @staticmethod
    def resolve_model_file(obj: Equipment):
        return obj.model_file.url if obj.model_file else None


@api.get("/equipment", response=list[EquipmentListOut])
def list_equipment(request):
    return Equipment.objects.all()


@api.get("/equipment/{slug}", response=EquipmentOut)
def get_equipment(request, slug: str):
    return get_object_or_404(
        Equipment.objects.prefetch_related("modules__components"), slug=slug
    )


@api.get("/components/{component_id}", response=ComponentOut)
def get_component(request, component_id: int):
    return get_object_or_404(Component, id=component_id)


@api.get("/search", response=list[ComponentOut])
def search(request, q: str):
    return Component.objects.filter(name__icontains=q) | Component.objects.filter(
        function__icontains=q
    )
