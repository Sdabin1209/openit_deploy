"""wiring/진입: e2e_verify_restore.py --secrets DIR --ports JSON --work DIR --run-id ID. 상태 파일과 토큰 파일을 읽어 컴포넌트 link_restore_verify 에 넘기고 결과를 출력한다. 종료 코드: 0 통과, 1 어긋남."""
import argparse
import json
import pathlib
import sys

from openit_deploy.components import link_restore_verify
from openit_deploy.wiring.call import call


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--secrets"); ap.add_argument("--ports"); ap.add_argument("--work"); ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    P, W = json.loads(a.ports), pathlib.Path(a.work)
    T = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
    u = lambda k: f"http://127.0.0.1:{P[k]}"
    req = {"run_id": a.run_id, "work": str(W), "state": json.loads((W / "state.json").read_text()),
           "urls": {"qa": u("qa"), "ops": u("ops"), "mr": u("mr"), "gate": u("gate")},
           "tokens": {"qa": T("qa-read-synthetic-data"), "ops": T("ops-ingest-survey-service"), "mr": T("model-registry-read-release-gate"), "gate": T("gate-read-survey-service")}}
    r = call(link_restore_verify, "RestoreVerifyRequest", "RestoreVerifyResult", req)
    for c in r["checks"]:
        print(f"  {'OK  ' if c['ok'] else 'FAIL'} {c['name']}" + (f": {c['detail']}" if not c["ok"] else ""))
    if not r["ok"]:
        return 1
    print("OK: 문항 2버전, Trace DUPLICATE, 모델 패키지·어댑터 해시, 활성 포인터(롤백된 릴리스)")
    return 0
