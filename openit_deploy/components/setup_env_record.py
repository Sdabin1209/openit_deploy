"""컴포넌트 setup_env_record: 영역 scripts/setup-env.sh 의 표준 출력에서 SetupEnvReport(마지막 비어 있지 않은 줄)를 골라 저장해도 되는지 판정한다. 입력 SetupEnvRecordRequest, 출력 SetupEnvRecordResult.
왜: deploy 가 이웃 영역의 .venv 위치·pytest·npm 같은 환경 모양을 짐작하지 않게 한다(구조 규칙 1, U43). 영역이 낸 보고는 계약 validator 로 한 번만 검증하고(검증은 wiring 이 계약 패키지로 해서 contract_errors 로 넘긴다) 읽는 쪽은 다시 검증하지 않는다(R7).
status: STORE(저장) / NO_LINE(출력 없음, 종료 2) / CONTRACT_VIOLATION(종료 1)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import SetupEnvRecordRequest, SetupEnvRecordResult

import json


def run(request: "SetupEnvRecordRequest") -> "SetupEnvRecordResult":
    lines = [l for l in request["stdout_lines"] if l.strip()]
    if not lines:
        return {"status": "NO_LINE", "message": f"{request['area']}: setup-env.sh 가 표준 출력에 아무것도 내지 않았다"}
    try:
        rep = json.loads(lines[-1])
    except ValueError:
        return {"status": "CONTRACT_VIOLATION", "message": f"{request['area']}: SetupEnvReport 계약 위반: 마지막 줄을 SetupEnvReport 로 읽지 못했다(JSON 아님)"}
    errs = list(request["contract_errors"])
    if not errs and rep.get("area") != request["area"]:
        errs = [f"보고의 area({rep.get('area')})가 영역 이름({request['area']})과 다르다"]
    if errs:
        return {"status": "CONTRACT_VIOLATION", "message": f"{request['area']}: SetupEnvReport 계약 위반: {'; '.join(errs[:3])}"}
    return {"status": "STORE", "report": rep}
