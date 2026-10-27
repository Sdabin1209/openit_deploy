#!/usr/bin/env bash
# 버전 표 드리프트 점검. 기준은 scripts/lib.sh 의 표(DEPLOY_BC_TAG, DEPLOY_BC_TAG_SD, DEPLOY_TE_TAG, DEPLOY_MR_TAG) 하나다.
# 형제 영역의 requirements*/lock/pyproject/Dockerfile/스크립트가 적은 boundary-contracts·turn-engine·model-runtime 태그를 읽기 전용으로 모아
# 표와 다르면 실패하고 파일:줄을 출력한다. 문서(*.md)와 시험·변경 이력은 보지 않는다(과거 기록이라 다를 수 있다).
# 대상 영역: 10개(kiosk-frontend·admin-console 의 Dockerfile ARG BOUNDARY_CONTRACT[S]=vX 포함).
# 사용: check-versions.sh        환경: CHECK_VERSIONS_WORKSPACE(시험용: 형제 폴더가 있는 곳, 기본 워크스페이스)
#   표를 덮어쓰는 환경 변수(BOUNDARY_TAG_ALL, MODEL_RUNTIME_TAG_ALL, TURN_ENGINE_TAG_ALL)는 무시하고 lib.sh 의 기본 표를 기준으로 삼는다.
set -uo pipefail
export DEPLOY_NO_DOCKER=1
unset BOUNDARY_TAG_ALL MODEL_RUNTIME_TAG_ALL TURN_ENGINE_TAG_ALL
source "$(dirname "$0")/lib.sh"
WS="${CHECK_VERSIONS_WORKSPACE:-$WORKSPACE}"
export WS EXP_BC="$DEPLOY_BC_TAG" EXP_BC_SD="$DEPLOY_BC_TAG_SD" EXP_TE="$DEPLOY_TE_TAG" EXP_MR="$DEPLOY_MR_TAG"
exec python3 - <<'PY'
import os, re, subprocess, sys
from pathlib import Path
ws = Path(os.environ["WS"])
TABLE = {"boundary-contracts": os.environ["EXP_BC"], "turn-engine": os.environ["EXP_TE"], "model-runtime": os.environ["EXP_MR"]}
REPOS = ["survey-service", "release-gate", "model-lab", "ops-feedback", "question-authoring", "synthetic-data", "turn-engine", "model-runtime", "kiosk-frontend", "admin-console"]
SD_BC = os.environ["EXP_BC_SD"]   # synthetic-data 는 자기가 고정한 boundary-contracts 태그(표의 별도 항목)와 맞춘다
NAMEFILE = re.compile(r"(^|/)(requirements[^/]*\.(txt|lock|in)|[^/]*\.lock|pyproject\.toml|Dockerfile[^/]*|[^/]*\.sh)$")
SKIP_DIR = re.compile(r"(^|/)(tests?|docs|\.venv|node_modules|build|dist)/")
PKG = re.compile(r"(boundary-contracts|turn-engine|model-runtime)(?:\.git)?@(v\d+\.\d+\.\d+)")
VAR = re.compile(r"\b(BOUNDARY|TURN_ENGINE|MODEL_RUNTIME)_(?:TAG|CONTRACTS?)\b[^\n]*?\b(v\d+\.\d+\.\d+)")
VARPKG = {"BOUNDARY": "boundary-contracts", "TURN_ENGINE": "turn-engine", "MODEL_RUNTIME": "model-runtime"}
def files(repo):
    d = ws / repo
    try:
        out = subprocess.run(["git", "-C", str(d), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
    except Exception:
        out = [str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [f for f in out if f and NAMEFILE.search(f) and not SKIP_DIR.search(f)]
bad = []; seen = 0; missing = []
for repo in REPOS:
    if not (ws / repo).is_dir(): missing.append(repo); continue
    for rel in files(repo):
        try: lines = (ws / repo / rel).read_text(errors="ignore").splitlines()
        except OSError: continue
        for n, line in enumerate(lines, 1):
            found = [(m.group(1), m.group(2)) for m in PKG.finditer(line)] + [(VARPKG[m.group(1)], m.group(2)) for m in VAR.finditer(line)]
            for pkg, tag in found:
                seen += 1
                exp = SD_BC if (repo == "synthetic-data" and pkg == "boundary-contracts") else TABLE[pkg]
                if tag != exp: bad.append(f"{repo}/{rel}:{n}: {pkg} {tag} (표: {exp})")
print(f"기준 표(scripts/lib.sh): boundary-contracts {TABLE['boundary-contracts']} (synthetic-data용 {SD_BC}), turn-engine {TABLE['turn-engine']}, model-runtime {TABLE['model-runtime']}")
print(f"검사한 태그 표기 {seen}건, 영역 {len(REPOS) - len(missing)}개" + (f", 폴더가 없어 건너뜀: {' '.join(missing)}" if missing else ""))
for b in bad: print("  다름:", b)
if bad: print(f"실패: 표와 다른 표기 {len(bad)}건. 영역의 해당 파일을 표에 맞추거나(영역 세션), 표를 바꾼다(deploy)"); sys.exit(1)
if seen == 0: print("실패: 태그 표기를 하나도 찾지 못했다(워크스페이스 경로 확인)"); sys.exit(2)
print("통과: 모든 표기가 표와 같다")
PY
