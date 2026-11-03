"""wiring/진입: check-all.sh 가 부르는 `check_all.py [--strict]`. 환경 변수(시험용)와 경로를 읽어 ConsistencyCheckRequest 로 만들고, 결과를 규칙별로 출력한다.
환경: CHECK_ALL_WORKSPACE, CHECK_ALL_ONLY(쉼표로 구분한 규칙 번호), CHECK_ALL_EXCLUDE, CHECK_ALL_ORDERED, CHECK_ALL_IMAGES(defer), CHECK_ALL_VERSIONS_CMD, CHECK_ALL_MR_PY, CHECK_ALL_LOG_DIR. 종료 코드: FAIL 이 있으면 1(--strict 면 SKIP 도)."""
import os
import pathlib
import subprocess
import sys

from openit_deploy.components import consistency_check
from openit_deploy.wiring import areas_file, setup_env
from openit_deploy.wiring.call import call

DEPLOY = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = DEPLOY / "scripts"


def workspace_of(deploy: pathlib.Path) -> pathlib.Path:
    """워크스페이스 = deploy 리포의 부모 폴더. 작업 트리(git worktree, deploy/build/wt-*)에서 돌면 부모는 deploy/build 이므로, 본 리포(git 공통 폴더의 부모)의 부모를 쓴다.
    왜: 작업 트리의 부모를 워크스페이스로 보면 그 안의 다른 작업 트리(.git 이 든 폴더)가 전부 '모르는 대상'이 된다."""
    if (deploy / ".git").is_file():   # 작업 트리는 .git 이 파일이다
        try:
            common = subprocess.run(["git", "-C", str(deploy), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
            return pathlib.Path(common).parent.parent
        except (OSError, subprocess.CalledProcessError):
            pass
    return deploy.parent


def build_request(argv) -> dict:
    ws = pathlib.Path(os.environ.get("CHECK_ALL_WORKSPACE") or workspace_of(DEPLOY))
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
