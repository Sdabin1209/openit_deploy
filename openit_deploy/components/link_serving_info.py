"""컴포넌트 link_serving_info (통신 컴포넌트, 보내는 쪽): 떠 있는 model-serving 의 GET /v1/info 로 적재된 릴리스 목록을 읽는다. 입력 ServingInfoRequest, 출력 ServingInfoResult.
openit_link.clients(HttpModelRuntime.info)로만 부른다(D118). 토큰은 요청에만 있다(D84)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ServingInfoRequest, ServingInfoResult

from openit_link.clients import HttpModelRuntime


def run(request: "ServingInfoRequest") -> "ServingInfoResult":
    info = HttpModelRuntime(request["url"], request["token"], timeout=request["timeout"]).info()
    return {"loaded": list(info.get("loaded") or [])}
