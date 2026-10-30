"""wiring/진입: check_link_pins.py [--ws DIR] — 각 영역 main 브랜치의 잠금 파일에서 openit-link 태그를 읽어 DEPLOY_LINK_TAG 와 대조한다(U59). 종료 코드: 0 모두 같다, 1 어긋남, 3 핀을 하나도 찾지 못함(검증하지 못함: 통과가 아니다).
읽기 전용: `git show main:<파일>`(없으면 HEAD)로 영역의 커밋된 내용을 본다. 작업 트리의 미커밋 변경은 보지 않는다(이웃의 정본은 main)."""
import argparse
import pathlib
import re
import subprocess
import sys

from openit_deploy.components import link_pin_check
from openit_deploy.wiring import areas_file
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]
CANDIDATE = re.compile(r"(^|/)(requirements[^/]*\.(txt|lock)|[^/]*\.lock|Dockerfile)$")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def read_area(repo: pathlib.Path) -> list:
    ref = "main" if _git(repo, "rev-parse", "--verify", "-q", "main").returncode == 0 else "HEAD"
    names = [f for f in _git(repo, "ls-tree", "-r", "--name-only", ref).stdout.splitlines() if CANDIDATE.search(f) and "/" not in f]
    return [{"path": f, "text": _git(repo, "show", f"{ref}:{f}").stdout} for f in names]


def deploy_link_tag() -> str:
    out = subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source "$1/scripts/lib.sh"; echo "$DEPLOY_LINK_TAG"', "_", str(ROOT)], capture_output=True, text=True, check=True).stdout
    return out.strip()


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--ws", default=str(ROOT.parent)); ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    ws = pathlib.Path(a.ws)
    names = areas_file.names(ws / "head" / "shared" / "areas.json", kinds={"python", "library"})
    names = [n for n in names if n != "link" and (ws / n / ".git").exists()]
    r = call(link_pin_check, "LinkPinCheckRequest", "LinkPinCheckResult",
             {"expected_tag": a.tag or deploy_link_tag(), "areas": [{"name": n, "files": read_area(ws / n)} for n in names]})
    print(f"기준 표(scripts/lib.sh): link {r['expected_tag']}")
    for x in r["areas"]:
        if x["status"] == "DIFF":
            for p in x["pins"]:
                if p["tag"] != r["expected_tag"]: print(f"  다름: {x['area']}/{p['path']}: {p['tag']} (표: {r['expected_tag']})")
        elif x["status"] == "NO_PIN":
            print(f"  핀 없음: {x['area']} (link 를 쓰지 않거나 잠금 위치를 알 수 없다: 검증하지 않았다)")
    if r["status"] == "DIFF":
        print(f"실패: 영역 잠금의 link 태그가 표와 다른 영역 {r['diff']}개. 영역이 표의 태그로 올리거나 표를 바꾼다(deploy)"); return 1
    if r["status"] == "NO_PIN":
        print("검증하지 못했다: 핀을 하나도 찾지 못했다 (통과가 아니다)"); return 3
    print(f"통과: link 핀이 있는 영역 {r['match']}개가 표와 같다 (핀 없음 {r['no_pin']}개는 검증하지 않았다)"); return 0
