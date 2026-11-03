"""컴포넌트 job_overlay: 이미지가 선언한 잡(라벨 io.openit.jobs, 계약 JobsDeclaration)에서 compose 잡 서비스의 command 와 시간 한도를 만든다(S10). 입력 JobOverlayRequest, 출력 JobOverlayResult.
왜: 잡을 어떤 명령으로 띄우는가는 영역이 안다. deploy 가 `python -m <모듈> <부명령>` 을 compose.yaml 에 손으로 적으면 영역의 모듈 구조를 deploy 가 아는 것이라 구조 규칙 1 을 어긴다.
시간 한도: 선언의 timeout_seconds, 없으면 RUNTIME R9.3 의 기본 3600초(시작값, 측정하지 않았다)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import JobOverlayRequest, JobOverlayResult

DEFAULT_TIMEOUT_SECONDS = 3600   # RUNTIME R9.3(시작값, 측정 안 함). 선언에 timeout_seconds 가 있으면 그 값이 이긴다


def run(request: "JobOverlayRequest") -> "JobOverlayResult":
    return {"services": {j["compose_service"]: {"command": list(j["declared"]["argv"]),
                                                "x-openit-timeout-seconds": j["declared"].get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)}
                         for j in request["jobs"]}}
