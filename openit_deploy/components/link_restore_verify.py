"""컴포넌트 link_restore_verify (통신 컴포넌트, 보내는 쪽): 복구한 저장소를 실제 서비스의 HTTP 로 다시 읽어 검증한다(E2E 9단계). 입력 RestoreVerifyRequest, 출력 RestoreVerifyResult.
샌드박스(docs/adr/0049): 이웃 서비스는 호스트 포트가 없다. 이웃 읽기는 그 서비스의 컨테이너 안에서 그 이미지의 계약 클라이언트(boundary_contracts.clients)로 한다.
요청의 urls 는 **컨테이너 안에서 본** 주소(예: http://127.0.0.1:8080)이고, 코드를 컨테이너에서 실행하는 일은 주입된 runner(키, 코드) -> stdout 이 한다(runner 는 입출력 스키마 밖의 운반 수단이다).
검증 항목: 문항 2버전과 해시, Trace 재전송이 DUPLICATE, 모델 패키지 매니페스트·어댑터 해시, 활성 포인터.
토큰은 코드(표준 입력)로만 컨테이너에 가고 결과·출력·프로세스 인자에 싣지 않는다(D84)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import RestoreVerifyRequest, RestoreVerifyResult

# 컨테이너 안에서 도는 코드의 공통 앞부분: 결과는 마지막 줄의 JSON 한 줄. 예외는 종류와 짧은 메시지만(값·토큰 없음)
_PRE = """import json, sys
try:
    from boundary_contracts import canonical
    from boundary_contracts.clients import {cls}
    URL, TOK = {url!r}, {tok!r}
"""
_POST = """
    out = {{"ok": True, **res}}
except Exception as e:
    out = {{"ok": False, "error": type(e).__name__ + ": " + str(e)[:120]}}
print(json.dumps(out))
"""


def _snippet(cls: str, url: str, tok: str, body: str) -> str:
    ind = "\n".join("    " + ln for ln in body.strip("\n").splitlines())
    return _PRE.format(cls=cls, url=url, tok=tok) + ind + _POST


_QA = """c = HttpQuestionReader(URL, TOK)
vs = c.list_versions({qs!r})[0]
res = {{"versions": [v["version"] for v in vs], "hashes_ok": all(canonical.content_hash(c.get_question_bank(v)) == v["content_hash"] for v in vs)}}"""
_OPS = """c = HttpTraceIngest(URL, TOK)
res = {{"status": c.send(json.loads({env!r}))["status"]}}"""
_MR = """import tempfile, pathlib
c = HttpModelRegistry(URL, TOK)
m = c.get_manifest({pid!r}, "1")
d = pathlib.Path(tempfile.mkdtemp()) / "restored-adapter"
res = {{"content_hash": m["content_hash"], "adapter_ok": canonical.directory_hash(c.open_adapter({pid!r}, "1", dest=d)) == m["adapter_hash"]}}"""
_GATE = """c = HttpReleaseReader(URL, TOK)
p = c.get_active_pointer()
res = {{"release_id": p["release_id"] if p else None}}"""


def run(request: "RestoreVerifyRequest", runner: Callable[[str, str], str]) -> "RestoreVerifyResult":
    u, t, s = request["urls"], request["tokens"], request["state"]
    checks = []

    def ask(key, cls, body):
        try:
            r = json.loads(runner(key, _snippet(cls, u[key], t[key], body)).strip().splitlines()[-1])
        except Exception as e:   # 컨테이너 실행 실패(종류와 짧은 메시지만)
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        return r

    def check(name, r, pred):
        if not r["ok"]:
            checks.append({"name": name, "ok": False, "detail": r["error"]}); return
        try:
            ok = bool(pred(r))
        except Exception as e:
            checks.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {str(e)[:120]}"}); return
        checks.append({"name": name, "ok": True} if ok else {"name": name, "ok": False, "detail": "기대와 다르다"})

    qa = ask("qa", "HttpQuestionReader", _QA.format(qs=f"qs-{request['run_id']}"))
    check("문항 2버전", qa, lambda r: r["versions"] == ["1", "2"])
    check("문항 해시", qa, lambda r: r["hashes_ok"])
    check("Trace 재전송은 DUPLICATE", ask("ops", "HttpTraceIngest", _OPS.format(env=json.dumps(s["trace_env"]))), lambda r: r["status"] == "DUPLICATE")
    pid = s["lora"]["LORA_A"]["id"]
    mr = ask("mr", "HttpModelRegistry", _MR.format(pid=pid))
    check("모델 패키지 해시", mr, lambda r: r["content_hash"] == s["lora"]["LORA_A"]["content_hash"])
    check("어댑터 해시", mr, lambda r: r["adapter_ok"])
    check("활성 포인터(롤백된 릴리스)", ask("gate", "HttpReleaseReader", _GATE), lambda r: r["release_id"] == s["releases"][s["qs"][0]["version"]])
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
