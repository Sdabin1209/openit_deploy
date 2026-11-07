"""wiring/진입: check_link_pins.py [--ws DIR] — 각 영역 main 브랜치의 잠금 파일에서 openit-link 태그를 읽어 DEPLOY_LINK_TAG 와 대조한다(U59). 종료 코드: 0 모두 같다, 1 어긋남, 3 핀을 하나도 찾지 못함(검증하지 못함: 통과가 아니다).
읽기 전용: 빌드 기록(build/images.env, 환경 LINK_PINS_IMAGES_ENV)이 있으면 영역마다 **빌드한 커밋**(기록의 revision)의 잠금 파일을 `git show <revision>:<파일>` 로 읽는다: 빌드한 것과 점검하는 것이 같아야 점검이다(D8b; 예전에는 main 을 읽어 영역 브랜치로 빌드한 이미지와 다른 핀을 봤다).
기록이 없는 영역(또는 기록에 없는 이미지의 영역)은 예전처럼 main(없으면 HEAD)을 읽고 "빌드 기록 없음"이라고 표시한다. 작업 트리의 미커밋 변경은 보지 않는다."""
from openit_deploy.wiring.workspace import workspace_of
import argparse
import os
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


# 이미지 이름 -> 소스 리포 (scripts/lib.sh 의 service_repo 와 같다: 이미지 이름과 영역 이름이 다른 셋)
IMAGE_REPO = {"model-registry": "model-lab", "dataset-store": "synthetic-data", "model-serving": "model-runtime", "model-serving-gpu": "model-runtime"}


def build_records(path: pathlib.Path) -> dict:
    """build/images.env 의 `이름 이미지 revision [도장]` 줄 -> {영역(리포): revision}. 파일이 없으면 {}."""
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split()
            if len(f) >= 3 and not line.lstrip().startswith("#"): out.setdefault(IMAGE_REPO.get(f[0], f[0]), f[2])
    except OSError:
        return {}
    return out


def read_area(repo: pathlib.Path, revision: str = "") -> list:
    if revision and _git(repo, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}").returncode == 0: ref = revision
    else: ref = "main" if _git(repo, "rev-parse", "--verify", "-q", "main").returncode == 0 else "HEAD"
    names = [f for f in _git(repo, "ls-tree", "-r", "--name-only", ref).stdout.splitlines() if CANDIDATE.search(f) and "/" not in f]
    return [{"path": f, "text": _git(repo, "show", f"{ref}:{f}").stdout} for f in names]


def deploy_link_tag() -> str:
    out = subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source "$1/scripts/lib.sh"; echo "$DEPLOY_LINK_TAG"', "_", str(ROOT)], capture_output=True, text=True, check=True).stdout
    return out.strip()


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--ws", default=str(workspace_of(ROOT))); ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    ws = pathlib.Path(a.ws)
    names = areas_file.names(ws / "head" / "shared" / "areas.json", kinds={"python", "library"})
    names = [n for n in names if n != "link" and (ws / n / ".git").exists()]
    rec_path = pathlib.Path(os.environ.get("LINK_PINS_IMAGES_ENV") or ROOT / "build" / "images.env")
    rec = build_records(rec_path)
    r = call(link_pin_check, "LinkPinCheckRequest", "LinkPinCheckResult",
             {"expected_tag": a.tag or deploy_link_tag(), "areas": [{"name": n, "files": read_area(ws / n, rec.get(n, ""))} for n in names]})
    print(f"기준 표(scripts/lib.sh): link {r['expected_tag']}")
    print("읽은 곳: " + (f"빌드 기록 {rec_path.name} 의 revision(빌드한 커밋) " + ", ".join(f"{n}@{rec[n][:7]}" for n in names if n in rec) if rec else "빌드 기록 없음: 영역 main(없으면 HEAD)") +
          ("" if not rec or all(n in rec for n in names) else f"; 빌드 기록 없음 → main: {', '.join(n for n in names if n not in rec)}"))
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
