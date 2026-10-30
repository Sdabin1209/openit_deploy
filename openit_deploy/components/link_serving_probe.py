"""컴포넌트 link_serving_probe (통신 컴포넌트, 보내는 쪽): 떠 있는 model-serving 에 extract·respond 를 한 번 부르고 호출 기록(ProbeRecord)으로 줄인다. 입력 ServingCallRequest, 출력 ProbeRecord.
이웃을 부르는 일은 openit_link.clients(HttpModelRuntime)로만 한다(D118). 발화·모델 원문은 기록에 담지 않는다. 토큰은 요청에만 있고 기록에 싣지 않는다(D84).
status: 성공은 200, 실패는 BoundaryError 코드(계약 클라이언트는 HTTP 상태 대신 오류 코드를 낸다)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ServingCallRequest, ProbeRecord

import time

from boundary_contracts.errors import BoundaryError
from openit_link.clients import HttpModelRuntime


def _record(status, outcome, attempts, details, latency):
    rec = {"status": status, "outcome": outcome or "-", "attempts": None if attempts is None else str(attempts), "reason": None, "violations": [], "latency_s": latency}
    if status == 200:
        rec["kind"] = "ok"
    else:
        rec["reason"] = details.get("reason")
        if status == "UNAVAILABLE" and rec["reason"] == "OUTPUT_INVALID":
            rec["kind"] = "output_invalid"; rec["violations"] = [str(v) for v in details.get("violations") or []]
        else:
            rec["kind"] = "other_error"
    return rec


def run(request: "ServingCallRequest") -> "ProbeRecord":
    rt = HttpModelRuntime(request["url"], request["token"], timeout=request["timeout"])
    body = request["body"]
    t = time.perf_counter()
    try:
        r = rt.extract(request["release_id"], body["input"], body["flow"], body["fields"]) if request["endpoint"] == "extract" else rt.respond(request["release_id"], body)
    except BoundaryError as e:
        return _record(e.code, None, None, e.details, time.perf_counter() - t)
    return _record(200, r.outcome, r.attempts, {}, time.perf_counter() - t)
