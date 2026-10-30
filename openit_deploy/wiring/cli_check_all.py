"""wiring/진입: check-all.sh 가 부르는 `check_all.py [--strict]`. 환경 변수(시험용)와 경로를 읽어 ConsistencyCheckRequest 로 만들고, 결과를 규칙별로 출력한다.
환경: CHECK_ALL_WORKSPACE, CHECK_ALL_ONLY(쉼표로 구분한 규칙 번호), CHECK_ALL_EXCLUDE, CHECK_ALL_ORDERED, CHECK_ALL_IMAGES(defer), CHECK_ALL_VERSIONS_CMD, CHECK_ALL_MR_PY, CHECK_ALL_LOG_DIR. 종료 코드: FAIL 이 있으면 1(--strict 면 SKIP 도)."""
import os
import pathlib
import sys

from openit_deploy.components import consistency_check
from openit_deploy.wiring import areas_file, setup_env
from openit_deploy.wiring.call import call

DEPLOY = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = DEPLOY / "scripts"


def build_request(argv) -> dict:
    ws = pathlib.Path(os.environ.get("CHECK_ALL_WORKSPACE") or DEPLOY.parent)
    af = ws / "head" / "shared" / "areas.json"
    return {"workspace": str(ws), "deploy_dir": str(DEPLOY), "areas_doc": areas_file.read(af) if af.is_file() else {"areas": []},
            "strict": "--strict" in argv, "only": [x for x in (os.environ.get("CHECK_ALL_ONLY") or "").split(",") if x],
            "exclude_file": os.environ.get("CHECK_ALL_EXCLUDE") or str(SCRIPTS / "check-all.exclude"),
            "ordered_file": os.environ.get("CHECK_ALL_ORDERED") or str(SCRIPTS / "check-all-ordered-schemas.txt"),
            "log_dir": os.environ.get("CHECK_ALL_LOG_DIR") or str(DEPLOY / "state" / "check-all"),
            "images_deferred": os.environ.get("CHECK_ALL_IMAGES") == "defer",
            "versions_cmd": os.environ.get("CHECK_ALL_VERSIONS_CMD") or str(SCRIPTS / "check-versions.sh"),
            "mr_python": os.environ.get("CHECK_ALL_MR_PY", "")}


def main(argv) -> int:
    req = build_request(list(argv))
    print(f"== check-all (워크스페이스 {req['workspace']})")
    r = call(consistency_check, "ConsistencyCheckRequest", "ConsistencyCheckResult", req, setup_env=setup_env)
    g = consistency_check.grouped
    for x in r["rules"]:
        print(f"{x['name']}: {x['status']}")
        print(f"  검증됨 {x['verified']}/{x['total']}, 어긋남 {x['failed']}, 대상 아님 {len(x['na'])}, 검증 안 함 {len(x['unverified'])}")
        if x["na"]:
            print(f"  대상 아님 이유: {g([(i['target'].split('#')[0] if '#' in i['target'] else i['target'], i['why']) for i in x['na']])}")
        if x["unverified"]:
            print(f"  검증 안 함 이유: {g([(i['target'], i['why']) for i in x['unverified']])}")
        for b in x["bad"]:
            print(f"  FAIL {b}")
        for i in x["info"]:
            print(f"  · {i}")
    print("-- 요약 (규칙별. 세 상태를 합치지 않는다. SKIP 은 '검증 안 함'이 있다는 뜻이고 통과로 세지 않는다)")
    for x in r["rules"]:
        print(f"  [{x['status']}] {x['name']}: 검증됨 {x['verified']}/{x['total']} | 어긋남 {x['failed']} | 대상 아님 {len(x['na'])} | 검증 안 함 {len(x['unverified'])}")
    print(f"-- 결과: FAIL {r['fail']}, SKIP {r['skip']}, PASS {r['pass']} / 규칙 {len(r['rules'])}개, 소요 {r['elapsed_s']:.1f}s")
    return r["exit_code"]
