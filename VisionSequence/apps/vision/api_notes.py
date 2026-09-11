"""站台共用工程筆記 API；登入讀取、流程編輯權限寫入。"""

from ninja import Body, Router

from apps.accounts.security import principal, require_feature
from apps.vision import notes

router = Router(tags=["engineering-notes"])


@router.get("/notes")
def list_notes(request, flow: int | None = None, part_number: str = "", kind: str = "", status: str = "", q: str = "", offset: int = 0):
    p = principal(request)
    notes.authorize(p)
    qs = notes.listing(flow=flow, part_number=part_number, kind=kind, status=status, q=q)
    start = max(0, offset)
    return {"items": [notes.out(row, p) for row in qs[start:start + 100]], "total": qs.count()}


@router.post("/notes", response={201: dict})
def create_note(request, payload: Body[dict]):
    p = require_feature(request, "flows.edit")
    return 201, notes.out(notes.create(p, payload), p)


@router.get("/notes/{note_id}")
def get_note(request, note_id: int):
    p = principal(request)
    notes.authorize(p)
    return notes.out(notes.get(note_id), p)


@router.patch("/notes/{note_id}")
def update_note(request, note_id: int, payload: Body[dict]):
    p = require_feature(request, "flows.edit")
    return notes.out(notes.update(p, note_id, payload), p)


@router.post("/notes/{note_id}/confirm")
def confirm_note(request, note_id: int):
    p = require_feature(request, "flows.edit")
    return notes.out(notes.transition(p, note_id, "confirm"), p)


@router.post("/notes/{note_id}/retract")
def retract_note(request, note_id: int):
    p = require_feature(request, "flows.edit")
    return notes.out(notes.transition(p, note_id, "retract"), p)
