"""컴포넌트 link_restore_verify (통신 컴포넌트, 보내는 쪽): 복구한 저장소를 실제 서비스의 HTTP 로 다시 읽어 검증한다(E2E 9단계). 입력 RestoreVerifyRequest, 출력 RestoreVerifyResult.
이웃을 부르는 일은 openit_link.clients 로만 한다(D118). 검증 항목: 문항 2버전과 해시, Trace 재전송이 DUPLICATE, 모델 패키지 매니페스트·어댑터 해시, 활성 포인터(롤백된 릴리스).
토큰은 요청에만 있고 결과·출력에 싣지 않는다(D84)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import RestoreVerifyRequest, RestoreVerifyResult

import pathlib

import boundary_contracts as bc  # noqa: F401  (계약 패키지 설치 확인용: canonical 해시)
from boundary_contracts import canonical
from openit_link.clients import HttpModelRegistry, HttpQuestionReader, HttpReleaseReader, HttpTraceIngest


def _check(checks, name, fn):
    try:
        ok = bool(fn())
        checks.append({"name": name, "ok": ok} if ok else {"name": name, "ok": False, "detail": "기대와 다르다"})
    except Exception as e:   # 실패 원인은 종류와 짧은 메시지만(값·토큰 없음)
        checks.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {str(e)[:120]}"})


def run(request: "RestoreVerifyRequest") -> "RestoreVerifyResult":
    u, t, s = request["urls"], request["tokens"], request["state"]
    checks = []
    qa = HttpQuestionReader(u["qa"], t["qa"])
    vs = qa.list_versions(f"qs-{request['run_id']}")[0]
    _check(checks, "문항 2버전", lambda: [v["version"] for v in vs] == ["1", "2"])
    _check(checks, "문항 해시", lambda: all(canonical.content_hash(qa.get_question_bank(v)) == v["content_hash"] for v in vs))
    _check(checks, "Trace 재전송은 DUPLICATE", lambda: HttpTraceIngest(u["ops"], t["ops"]).send(s["trace_env"])["status"] == "DUPLICATE")
    mr = HttpModelRegistry(u["mr"], t["mr"]); pid = s["lora"]["LORA_A"]["id"]
    m = mr.get_manifest(pid, "1")
    _check(checks, "모델 패키지 해시", lambda: m["content_hash"] == s["lora"]["LORA_A"]["content_hash"])
    _check(checks, "어댑터 해시", lambda: canonical.directory_hash(mr.open_adapter(pid, "1", dest=pathlib.Path(request["work"]) / "restored-adapter")) == m["adapter_hash"])
    ptr = HttpReleaseReader(u["gate"], t["gate"]).get_active_pointer()
    _check(checks, "활성 포인터(롤백된 릴리스)", lambda: ptr and ptr["release_id"] == s["releases"][s["qs"][0]["version"]])
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
