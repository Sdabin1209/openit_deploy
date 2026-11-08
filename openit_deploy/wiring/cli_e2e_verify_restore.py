"""wiring/진입: e2e_verify_restore.py --secrets DIR --ports JSON --work DIR --run-id ID --project P --gw-ca FILE. 상태 파일과 토큰 파일을 읽어 컴포넌트 link_restore_verify 에 넘기고 결과를 출력한다. 종료 코드: 0 통과, 1 어긋남."""
import argparse
import json
import pathlib
import sys

from openit_deploy.components import link_restore_verify
from openit_deploy.wiring.call import call


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--secrets"); ap.add_argument("--ports"); ap.add_argument("--work"); ap.add_argument("--run-id")
    ap.add_argument("--project", required=True); ap.add_argument("--docker", default="docker"); ap.add_argument("--root")
    # 왜 필수: exec_py 의 클라이언트 컨테이너가 영역 게이트웨이 HTTPS 를 검증할 신뢰 루트(R1.3)다. 없으면 exec_py 가 RuntimeError 를 낸다(e2e.sh 는 단계 1~8 과 같은 trust.crt 를 준다)
    ap.add_argument("--gw-ca", required=True)
    a = ap.parse_args(argv)
    W = pathlib.Path(a.work)
    T = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
    # 샌드박스(docs/adr/0049): 호스트 포트를 쓰지 않는다. 읽기는 각 서비스와 같은 망의 클라이언트 컨테이너에서 그 서비스의 영역 게이트웨이(https://<서비스>, R1.1~R1.3)로, 운반은 e2e_sandbox.exec_py
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
    import e2e_sandbox as S
    import os
    S.init(project=a.project, secrets=a.secrets, gw_ca=a.gw_ca, docker=a.docker, secrets_gid=os.environ.get("SECRETS_GID", ""), **({"root": a.root} if a.root else {}))
    SVC = {"qa": "question-authoring", "ops": "ops-feedback", "mr": "model-registry", "gate": "release-gate"}
    u = lambda k: "https://" + SVC[k]   # 영역 게이트웨이 주소: exec_py 가 SELF(@SELF@) 를 바꿔 넣는 값과 같은 규칙. 앱의 loopback 포트(127.0.0.1:8080)로 우회하지 않는다
    req = {"run_id": a.run_id, "work": str(W), "state": json.loads((W / "state.json").read_text()),
           "urls": {"qa": u("qa"), "ops": u("ops"), "mr": u("mr"), "gate": u("gate")},
           "tokens": {"qa": T("qa-read-synthetic-data"), "ops": T("ops-ingest-survey-service"), "mr": T("model-registry-read-release-gate"), "gate": T("gate-read-survey-service")}}
    r = call(link_restore_verify, "RestoreVerifyRequest", "RestoreVerifyResult", req, runner=lambda key, code: S.exec_py(SVC[key], code, timeout=120))
    for c in r["checks"]:
        print(f"  {'OK  ' if c['ok'] else 'FAIL'} {c['name']}" + (f": {c['detail']}" if not c["ok"] else ""))
    if not r["ok"]:
        return 1
    print("OK: 문항 2버전, Trace DUPLICATE, 모델 패키지·어댑터 해시, 활성 포인터(롤백된 릴리스)")
    return 0
