"""컴포넌트 area_list: 영역 목록(AreasDoc)에서 조건(kind, 버전 열차, 제외)에 맞는 영역 이름을 고른다.
입력 AreaListRequest, 출력 AreaListResult (schemas/). 왜 따로: 영역 이름을 스크립트마다 따로 적으면 영역을 더할 때 한 곳을 빠뜨린다(정본은 head/shared/areas.json 하나, 읽는 일은 wiring).
알 수 없는 kind 는 스키마(AreasDoc.kind enum)가 거부한다. 손 검사 없음."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import AreaListRequest, AreaListResult



def run(request: "AreaListRequest") -> "AreaListResult":
    kinds, exclude = set(request.get("kinds") or ()), set(request.get("exclude") or ())
    return {"names": [a["name"] for a in request["areas_doc"]["areas"]
                      if (not kinds or a["kind"] in kinds) and (not request.get("train") or a["version_train"]) and a["name"] not in exclude]}
