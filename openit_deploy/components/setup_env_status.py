"""컴포넌트 setup_env_status: 저장된 SetupEnvReport 로 영역의 환경이 준비됐는지 판정하고 환경 파이썬 위치를 알려 준다. 입력 SetupEnvStatusRequest, 출력 SetupEnvStatusResult.
보고 읽기와 환경 경로 존재 확인(바깥 자원)은 wiring 이 하고 결과(report, env_path_exists)만 받는다. python-venv 표준 배치는 <path>/bin/python 이다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import SetupEnvStatusRequest, SetupEnvStatusResult



def run(request: "SetupEnvStatusRequest") -> "SetupEnvStatusResult":
    area, rep = request["area"], request["report"]
    fix = f"(해결: bash scripts/prepare-areas.sh {area})"
    if rep is None:
        return {"status": "NO_REPORT", "reason": f"{area} 의 setup-env 보고가 없다 {fix}"}
    if rep.get("status") != "ok":
        return {"status": "SETUP_FAILED", "reason": f"{area} 의 setup-env 가 실패했다(status={rep.get('status')}, exit_code={rep.get('exit_code')}) {fix}"}
    env = rep["environment"]
    if not request["env_path_exists"]:
        return {"status": "PATH_MISSING", "reason": f"{area} 의 환경 경로 {env['path']} 가 없다 {fix}"}
    return {"status": "READY", "reason": "", "python": f"{env['path']}/bin/python" if env["kind"] == "python-venv" else None}
