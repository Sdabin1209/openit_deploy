#!/usr/bin/env bash
# deploy 자체 점검을 한 번에 돌린다(커밋 전에 실행한다). 목록의 정본은 scripts/self-checks.list 한 곳이고 e2e.sh 도 같은 목록을 쓴다.
# 사용: scripts/run-self-checks.sh [--print]     --print: 실행하지 않고 "설명<TAB>명령" 줄만 낸다(e2e.sh 가 읽는다)
# 종료 코드: 0 전부 통과, 1 하나라도 실패(실패한 것의 이름과 출력 끝을 보인다), 2 목록을 읽지 못함.
# 이 묶음에 없는 것(이유): publish·check-compose·check-versions·check-exposure 는 빌드한 이미지와 레지스트리가 있어야 의미가 있어 e2e.sh 의 준비 단계에서 직접 돈다.
#   레지스트리·기동한 스택이 필요한 시험(test-publish, test-backup, test-monitoring 전체 등)도 이 목록에 없다. 전체 E2E(e2e.sh)는 이 묶음과 별개다.
# 필요한 것: deploy .venv(계약 패키지가 설치된 파이썬), docker 데몬(일부 시험), 이웃 영역이 deploy 옆에 있는 작업 공간(check-all 계열). 작업 트리가 deploy/build/ 아래면 AREAS_FILE 을 지정한다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
VENV=${VENV:-$DEPLOY_ROOT/.venv}; [ -x "$VENV/bin/python" ] || VENV=$(cd "$(git -C "$DEPLOY_ROOT" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)/.venv
LIST="$HERE/self-checks.list"
[ -s "$LIST" ] || { echo "목록을 읽지 못했다: $LIST" >&2; exit 2; }
entries() { grep -vE '^\s*(#|$)' "$LIST" | awk -F' :: ' '{d=$1; c=substr($0, length($1)+5); printf "%s\t%s\n", d, c}'; }
if [ "${1:-}" = --print ]; then entries; exit 0; fi
export DEPLOY_ROOT VENV
FAILS=0; N=0; FAILED=()
while IFS=$'\t' read -r d c; do
  N=$((N+1)); out=$(bash -c "$c" 2>&1); rc=$?
  if [ $rc = 0 ]; then echo "  [PASS] $d"; else echo "  [FAIL] $d (종료 $rc)"; printf '%s\n' "$out" | tail -8 | sed 's/^/         /'; FAILS=$((FAILS+1)); FAILED+=("$d"); fi
done < <(entries)
echo; if [ $FAILS = 0 ]; then echo "run-self-checks: 전부 통과 ($N개)"; else echo "run-self-checks: 실패 $FAILS개 / $N개"; printf '  - %s\n' "${FAILED[@]}"; exit 1; fi
