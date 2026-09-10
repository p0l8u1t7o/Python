"""站台佇列查詢與清空；權限與稽核只在 API 呼叫執行緒處理。"""

from ninja import Router

from apps.accounts.security import principal, require_feature
from apps.core import audit
from apps.core.errors import ValidationError
from apps.vision import queues

router = Router(tags=["queues"])


@router.get("/queues")
def list_queues(request):
    require_feature(request, "integration")
    return {"items": queues.store.snapshot()}


@router.delete("/queues/{name}")
def clear_queue(request, name: str):
    if not principal(request).can("connections"):
        require_feature(request, "flows.edit")
    try:
        removed = queues.store.clear(name)
    except queues.QueueError as exc:
        raise ValidationError(str(exc), code="bad_queue") from None
    audit.record(request, "queue.clear", "queue", target_id=name, summary=f"Cleared queue {name}", detail={"removed": removed})
    return {"name": name, "removed": removed}
