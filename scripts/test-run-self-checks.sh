#!/usr/bin/env bash
# run-self-checks.sh 의 종료 코드 집계 시험: 77(SKIP)은 PASS 가 아니고, 실패 없이 SKIP 이 있으면 묶음도 0 이 아니다(77), 실패가 있으면 1.
# 입력: 임시 폴더에 run-self-checks.sh·lib.sh 사본과 시험용 목록을 두고 돌린다(실제 목록·시험은 부르지 않는다; Docker 불필요). 판정은 종료 코드로 한다.
# 변이: 집계의 77 분기를 지운 사본은 SKIP 을 FAIL 로 세므로 아래 단언이 실패해야 한다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; F=0
ok() { echo "  ok   $*"; }; bad() { echo "  FAIL $*"; F=$((F+1)); }
mkrun() {   # mkrun <폴더> <목록 줄...> : 사본 스크립트 폴더를 만든다
  local d=$1; shift; mkdir -p "$d"; cp "$HERE/run-self-checks.sh" "$HERE/lib.sh" "$d/"; printf '%s\n' "$@" > "$d/self-checks.list"
}
runit() { local d=$1; local o; o=$(VENV=/nonexistent bash "$d/run-self-checks.sh" 2>&1); RC=$?; OUT=$o; }
mkrun "$T/a" "통과 :: true" "건너뜀 :: exit 77"; runit "$T/a"
[ $RC = 77 ] && ok "실패 없이 SKIP 이 있으면 77" || bad "SKIP 만 있을 때 종료 $RC"
grep -q '\[SKIP\] 건너뜀' <<<"$OUT" && ! grep -q '\[PASS\] 건너뜀' <<<"$OUT" && ok "SKIP 은 PASS 로 세지 않고 따로 보인다" || bad "SKIP 표시"
mkrun "$T/b" "통과 :: true"; runit "$T/b"
[ $RC = 0 ] && ok "전부 통과면 0" || bad "전부 통과인데 종료 $RC"
mkrun "$T/c" "실패 :: exit 3" "건너뜀 :: exit 77"; runit "$T/c"
[ $RC = 1 ] && ok "실패가 있으면 SKIP 이 있어도 1" || bad "실패+SKIP 종료 $RC"
mkrun "$T/m" "건너뜀 :: exit 77"; sed -i 's/elif \[ \$rc = 77 \]/elif false/' "$T/m/run-self-checks.sh"; runit "$T/m"
[ $RC = 1 ] && ok "변이(77 분기 제거)는 SKIP 을 FAIL 로 센다: 위 단언이 잡는다" || bad "변이가 효과 없음(종료 $RC)"
[ $F = 0 ] && { echo "통과: run-self-checks 집계 시험"; exit 0; } || { echo "실패: $F건"; exit 1; }
