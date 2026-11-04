"""컴포넌트 job_overlay: 이미지가 선언한 잡(라벨 io.openit.jobs, 계약 JobsDeclaration)에서 compose 잡 서비스의 command·시간 한도·실행 주기를 만든다(S10). 입력 JobOverlayRequest, 출력 JobOverlayResult.
왜: 잡을 어떤 명령으로 띄우는가와 얼마나 걸리는가는 영역이 안다. 언제 띄우는가(주기)는 deploy 의 일정이고 영역은 그것을 모른다(구조 규칙 4). deploy 가 선언된 상한보다 긴 주기를 규칙으로 고른다.
시간 상한: 선언의 timeout_seconds, 없으면 RUNTIME R9.3 의 기본 3600초(시작값, 측정하지 않았다).
주기 규칙(RUNTIME R9.3: 상한은 주기보다 짧아야 R10.12 의 겹침 방지가 다음 주기를 막지 않는다): 주기 = max(기본 주기, 상한보다 큰 가장 작은 300초 배수). 300초(5분)는 타이머 AccuracySec 와 사람이 읽는 단위를 맞춘 선택이고 측정한 값이 아니다(ADR 0064)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import JobOverlayRequest, JobOverlayResult

DEFAULT_TIMEOUT_SECONDS = 3600   # RUNTIME R9.3(시작값, 측정 안 함). 선언에 timeout_seconds 가 있으면 그 값이 이긴다
PERIOD_STEP_SECONDS = 300


def period_for(timeout: int, base: int) -> int:
    return max(base, (timeout // PERIOD_STEP_SECONDS + 1) * PERIOD_STEP_SECONDS)


def run(request: "JobOverlayRequest") -> "JobOverlayResult":
    out = {}
    for j in request["jobs"]:
        timeout = j["declared"].get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        out[j["compose_service"]] = {"command": list(j["declared"]["argv"]), "x-openit-timeout-seconds": timeout,
                                     "x-openit-period-seconds": period_for(timeout, j.get("base_period_seconds", 0))}
    return {"services": out}
