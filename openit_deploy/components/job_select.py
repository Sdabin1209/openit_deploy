"""컴포넌트 job_select: 이미지 라벨 io.openit.jobs 에서 이름이 맞는 잡 하나를 고른다. 입력 JobSelectRequest, 출력 JobSelectResult.
영역의 모듈 이름·cwd·설정 위치를 deploy 가 모른다(U43): 잡 선언(계약 JobsDeclaration)의 argv·config 를 그대로 쓴다. 선언이 계약을 따르는지는 내는 쪽(wiring)이 계약 validator 로 검증해 넘긴다(declaration_errors)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import JobSelectRequest, JobSelectResult

import json


def run(request: "JobSelectRequest") -> "JobSelectResult":
    labels = request["labels"]
    if "io.openit.jobs" not in labels:
        return {"status": "NO_JOBS_LABEL"}
    if request.get("declaration_errors"):
        return {"status": "INVALID_DECLARATION", "message": request["declaration_errors"][0]}
    decl = json.loads(labels["io.openit.jobs"])
    job = next((j for j in decl["jobs"] if j["name"] == request["job_name"]), None)
    if job is None:
        return {"status": "NO_SUCH_JOB", "available": [j["name"] for j in decl["jobs"]]}
    return {"status": "OK", "job": job}
