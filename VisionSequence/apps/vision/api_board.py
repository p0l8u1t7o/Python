"""看板資料的 API：整合端自建 UI、網頁總覽頁與全螢幕看板都從這一個端點拿齊。

    GET /vision/flows/{id}/board    設定＋最新一次 run（影像 ref、標記、判定）＋要顯示的數值（公差判定已算好）＋今日良率＋變數

設定本身在 PATCH /vision/flows/{id} 的 `board` 欄位（flows.edit）。
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.core.errors import NotFound
from apps.vision import board, variables
from apps.vision.api import _visible_flows, get_flow
from apps.vision.runner import runner

router = Router(tags=["board"])


@router.get("/flows/{flow_id}/board")
def flow_board(request: HttpRequest, flow_id: int):
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    rt = runner.runtime(flow.id)
    latest = rt.recent[-1].to_dict(include_node_outputs=True) if rt.recent else None
    variables.store.ensure_loaded(flow.id)
    return board.build(flow, latest, variables=variables.store.snapshot(flow.id), stats=rt.stats.to_dict())
