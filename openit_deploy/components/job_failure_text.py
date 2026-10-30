"""컴포넌트 job_failure_text: 잡 종료 코드와 stderr 를 한 줄 설명으로 바꾼다. 입력 JobFailureRequest, 출력 JobFailureResult.
2: stderr 마지막 줄이 SyntheticJobError JSON(설정 오류). 3·75: BoundaryError 레코드. 그 밖: 계약에 정한 형식이 없으므로 stderr 끝을 그대로 보인다(비밀은 잡이 내지 않는다: D84).
파싱·검증에 실패하면 그 사실을 적고 원문 끝을 보인다(읽지 못한 것을 읽은 것처럼 쓰지 않는다). 마지막 줄의 계약 검증은 wiring 이 계약 validator 로 해서 tail_errors 로 넘긴다(JSON 이 아니면 tail_json=false)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import JobFailureRequest, JobFailureResult

import json


def run(request: "JobFailureRequest") -> "JobFailureResult":
    rc, tail = request["returncode"], request["stderr_tail"]
    if rc in (2, 3, 75):
        name = "SyntheticJobError" if rc == 2 else "BoundaryError"
        if not request["tail_is_json"]:
            return {"text": f"잡 종료 코드 {rc}: stderr 마지막 줄이 JSON 이 아니라 {name} 로 읽지 못했다: {tail[:200]}"}
        if request["tail_errors"]:
            return {"text": f"잡 종료 코드 {rc}: stderr 마지막 줄이 {name} 계약을 어긴다({request['tail_errors'][0][:80]}): {tail[:200]}"}
        rec = json.loads(tail)
        if rc == 2:
            return {"text": f"잡 종료 코드 2 (설정 오류 {rec['error']}): {rec['message']}"}
        return {"text": f"잡 종료 코드 {rc} (BoundaryError {rec['code']}, 재시도 {'가능' if rec['retryable'] else '불가'}): {rec['message']}"}
    return {"text": f"잡 종료 코드 {rc}: {tail[:200]}"}
