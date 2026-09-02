"""ninja API 根：統一錯誤格式、選填 API 金鑰。"""

from __future__ import annotations

from ninja import NinjaAPI
from ninja.errors import ValidationError as NinjaValidationError
from ninja.renderers import BaseRenderer

import orjson

from apps.accounts import security
from apps.core.errors import APIError


class ORJSONRenderer(BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)


api = NinjaAPI(
    title="VisionSequence API",
    version="1.0",
    renderer=ORJSONRenderer(),
    auth=security.auth,
    urls_namespace="api",
)


@api.exception_handler(APIError)
def _api_error(request, exc: APIError):
    return api.create_response(request, exc.to_dict(), status=exc.status_code)


@api.exception_handler(NinjaValidationError)
def _ninja_validation(request, exc: NinjaValidationError):
    return api.create_response(
        request,
        {"error": {"code": "validation_error", "message": "請求格式錯誤", "details": exc.errors}},
        status=422,
    )


from apps.accounts.api import lock_router, router as auth_router, users_router  # noqa: E402
from apps.vision.api import router as vision_router  # noqa: E402
from apps.vision.api_more import router as more_router  # noqa: E402
from apps.vision.api_recipes import router as recipes_router  # noqa: E402
from apps.comm.api import router as comm_router  # noqa: E402
from apps.vision.api_flowio import router as flowio_router  # noqa: E402
from apps.golden.api import router as golden_router  # noqa: E402
from apps.vision.dl.api import router as dl_router  # noqa: E402
from apps.vision.agent.api import router as agent_router  # noqa: E402

api.add_router("/auth", auth_router)
api.add_router("/users", users_router)
api.add_router("/vision/lock", lock_router)
# flow-io 與 golden 先註冊：`/flows/import` 不能被 `/flows/{flow_id}` 吃掉（ninja 路徑參數不帶型別）。
api.add_router("/vision", flowio_router)
api.add_router("/vision", golden_router)
api.add_router("/vision", recipes_router)
api.add_router("/vision", vision_router)
api.add_router("/vision", more_router)
api.add_router("/vision", comm_router)
api.add_router("/vision", dl_router)
api.add_router("/vision", agent_router)
