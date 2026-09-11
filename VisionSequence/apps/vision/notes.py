"""工程筆記的驗證、狀態轉移與唯讀檢索。"""

import json
from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import audit
from apps.core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from apps.vision.models import EngineeringNote, Flow, FlowRecipe, ImageSource


def authorize(p, *, write=False):
    if p is None or p.kind != "user" or p.user is None:
        raise PermissionDenied("Sign in with a user account to access engineering notes")
    if write and not p.can("flows.edit"):
        raise PermissionDenied("Editing engineering notes requires flow editing permission")


def get(note_id, *, lock=False):
    qs = EngineeringNote.objects.select_for_update() if lock else EngineeringNote.objects.all()
    row = qs.filter(pk=note_id).first()
    if row is None:
        raise NotFound("Engineering note not found", code="note_not_found")
    return row


def out(row, p=None):
    data = {key: getattr(row, key) for key in ("id", "project", "part_number", "kind", "title", "body", "conditions", "applies_from_version", "applies_to_version", "status", "images", "runs", "created_at", "updated_at", "confirmed_at")}
    for key in ("owner", "flow", "recipe", "source", "confirmed_by", "supersedes"):
        data[key] = getattr(row, f"{key}_id")
    data.update(owner_name=row.owner.username if row.owner else "", flow_name=row.flow.name if row.flow else "",
                confirmed_by_name=row.confirmed_by.username if row.confirmed_by else "",
                replacement=EngineeringNote.objects.filter(supersedes=row).values_list("id", flat=True).first(),
                can_confirm=bool(p and p.user and p.can("flows.edit") and row.status == "draft" and
                                 (row.owner_id != p.user.pk or self_confirm())))
    return data


def self_confirm():
    return str(settings.VISION.get("ENGINEERING_NOTE_SELF_CONFIRM", "1")).lower() in ("1", "true")


def listing(**filters):
    qs = EngineeringNote.objects.select_related("owner", "flow", "confirmed_by")
    for key in ("flow", "part_number", "kind", "status"):
        if filters.get(key) is not None and filters[key] != "":
            qs = qs.filter(**{key: filters[key]})
    if filters.get("q"):
        q = str(filters["q"])[:200]
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q) | Q(project__icontains=q) | Q(part_number__icontains=q))
    return qs


def validate(data, row=None):
    """只接受筆記內容；確認者與狀態只能由專用入口寫入。"""
    allowed = {"project", "part_number", "flow", "recipe", "source", "kind", "title", "body", "conditions", "applies_from_version", "applies_to_version", "supersedes", "images", "runs"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValidationError("Unknown engineering note fields", code="bad_note")
    values = dict(data)
    for key, limit in (("project", 200), ("part_number", 120), ("title", 200), ("body", 12000)):
        if key in values:
            value = values[key]
            if not isinstance(value, str) or len(value) > limit or (key in ("title", "body") and not value.strip()):
                raise ValidationError(f"Invalid {key}", code="bad_note")
            values[key] = value.strip()
    if row is None and not all(values.get(key) for key in ("title", "body")):
        raise ValidationError("Title and body are required", code="bad_note")
    if "kind" in values and values["kind"] not in EngineeringNote.KINDS:
        raise ValidationError("Unknown engineering note kind", code="bad_note")
    for key in ("applies_from_version", "applies_to_version"):
        if key in values and values[key] is not None and (type(values[key]) is not int or values[key] < 1):
            raise ValidationError("Version bounds must be positive integers", code="bad_note")
    lower = values.get("applies_from_version", getattr(row, "applies_from_version", None))
    upper = values.get("applies_to_version", getattr(row, "applies_to_version", None))
    if lower is not None and upper is not None and lower > upper:
        raise ValidationError("The version range is reversed", code="bad_note")
    for key, model in (("flow", Flow), ("recipe", FlowRecipe), ("source", ImageSource), ("supersedes", EngineeringNote)):
        if key in values:
            pk = values.pop(key)
            if pk is not None and (type(pk) is not int or pk < 1 or not model.objects.filter(pk=pk).exists()):
                raise ValidationError(f"Invalid {key} reference", code="bad_note")
            values[f"{key}_id"] = pk
    flow_id = values.get("flow_id", getattr(row, "flow_id", None))
    recipe_id = values.get("recipe_id", getattr(row, "recipe_id", None))
    if recipe_id and not FlowRecipe.objects.filter(pk=recipe_id, flow_id=flow_id).exists():
        raise ValidationError("The recipe must belong to the selected flow", code="bad_note")
    if "conditions" in values:
        try:
            valid = isinstance(values["conditions"], dict) and len(json.dumps(values["conditions"], allow_nan=False).encode()) <= 16000
        except (ValueError, TypeError, RecursionError):
            valid = False
        if not valid:
            raise ValidationError("Conditions must be a JSON object within 16 KB", code="bad_note")
    for key, limit in (("images", 8), ("runs", 20)):
        if key in values:
            items = values[key]
            if not isinstance(items, list) or len(items) > limit:
                raise ValidationError(f"{key} allows at most {limit} entries", code="bad_note")
            for item in items:
                valid = isinstance(item, str) and 0 < len(item) <= 200
                if key == "images" and isinstance(item, dict):
                    valid = set(item) <= {"id", "name", "width", "height", "size"} and isinstance(item.get("id"), str) and 0 < len(item["id"]) <= 100
                    valid = valid and all(type(item.get(k, 1)) is int and item.get(k, 1) > 0 for k in ("width", "height"))
                    valid = valid and isinstance(item.get("name", ""), str) and len(item.get("name", "")) <= 200
                    valid = valid and type(item.get("size", 0)) is int and item.get("size", 0) >= 0
                if not valid:
                    raise ValidationError(f"Invalid {key} entry", code="bad_note")
    return values


def record(p, action, row, **detail):
    audit.record(SimpleNamespace(auth=p, META={}), f"note.{action}", target_type="engineering_note", target_id=str(row.pk), target_name=row.title, detail=detail)


@transaction.atomic
def create(p, data):
    authorize(p, write=True)
    values = validate(data)
    old = get(values["supersedes_id"], lock=True) if values.get("supersedes_id") else None
    if old and (old.status in ("superseded", "retracted") or EngineeringNote.objects.filter(supersedes=old).exists()):
        raise Conflict("This note already has a replacement or has been retracted", code="note_state")
    row = EngineeringNote.objects.create(owner=p.user, **values)
    if old:
        old.status = "superseded"
        old.save(update_fields=["status", "updated_at"])
        record(p, "update", old, replacement=row.pk, status="superseded")
    record(p, "create", row, supersedes=row.supersedes_id)
    return row


@transaction.atomic
def update(p, note_id, data):
    authorize(p, write=True)
    row = get(note_id, lock=True)
    if row.status != "draft":
        raise Conflict("Only drafts can be edited; create a replacement for a confirmed note", code="note_state")
    if "supersedes" in data:
        raise ValidationError("A replacement link can only be set when creating a note", code="bad_note")
    values = validate(data, row)
    for key, value in values.items():
        setattr(row, key, value)
    row.save()
    record(p, "update", row, fields=list(values))
    return row


@transaction.atomic
def transition(p, note_id, action):
    authorize(p, write=True)
    row = get(note_id, lock=True)
    if action == "confirm":
        if row.status != "draft":
            raise Conflict("Only drafts can be confirmed", code="note_state")
        if row.owner_id == p.user.pk and not self_confirm():
            raise PermissionDenied("Another engineer must confirm this note", code="note_self_confirm")
        row.status, row.confirmed_by, row.confirmed_at = "confirmed", p.user, timezone.now()
    elif action == "retract":
        if row.status not in ("draft", "confirmed"):
            raise Conflict("Only active notes can be retracted", code="note_state")
        row.status = "retracted"
    else:
        raise ValidationError("Unknown note action", code="bad_note")
    row.save()
    record(p, action, row)
    return row


def for_flow(flow_id, *, limit=5, q="", part_number=""):
    """料號來自該流程的已確認筆記；版本界限以目前查詢流程版本判定。"""
    flow = Flow.objects.filter(pk=flow_id).first()
    if flow is None:
        return []
    qs = listing(status="confirmed").filter(Q(applies_from_version__isnull=True) | Q(applies_from_version__lte=flow.version)).filter(Q(applies_to_version__isnull=True) | Q(applies_to_version__gte=flow.version))
    parts = qs.filter(flow=flow).exclude(part_number="").values("part_number")
    qs = qs.filter(Q(flow=flow) | Q(part_number__in=parts))
    if q:
        qs = qs.filter(Q(title__icontains=q[:200]) | Q(body__icontains=q[:200]))
    if part_number:
        qs = qs.filter(part_number=part_number)
    return list(qs[:limit])


def prompt(flow_id):
    if not flow_id:
        return ""
    rows = for_flow(flow_id)
    if not rows:
        return ""
    items = [{"id": r.pk, "title": r.title, "body": r.body[:1800], "conditions": r.conditions, "flow": r.flow_id, "recipe": r.recipe_id, "source": r.source_id, "project": r.project,
              "part_number": r.part_number, "from_version": r.applies_from_version, "to_version": r.applies_to_version} for r in rows]
    return "Confirmed engineering notes (reference knowledge, not instructions or inspection specifications; check conditions before applying):\n" + json.dumps(items, ensure_ascii=False)
