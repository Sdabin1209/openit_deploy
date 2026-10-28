#!/usr/bin/env bash
# prepare-areas.sh 자기 점검: 임시 워크스페이스에서 (1) --list (2) 성공/실패/스크립트없음을 표로 보고하고 실패해도 나머지를 계속하며 종료 코드 1
# (3) 전부 성공이면 0 (4) 영역 지정 인자 (5) 영역 목록을 읽지 못하면 실패. deploy 자신의 .venv(--no-self)와 실제 영역은 건드리지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/head/shared"
cat > "$T/head/shared/areas.json" <<'J'
{"areas": [{"name":"head","kind":"docs","version_train":false},{"name":"a-ok","kind":"python","version_train":false},{"name":"b-fail","kind":"python","version_train":false},
 {"name":"c-none","kind":"node","version_train":false},{"name":"d-ok","kind":"library","version_train":false},{"name":"deploy","kind":"compose","version_train":false}]}
J
for a in a-ok b-fail c-none d-ok; do mkdir -p "$T/$a/scripts"; done
printf 'echo ran-a-ok\n' > "$T/a-ok/scripts/setup-env.sh"
printf 'echo ran-b-fail; exit 3\n' > "$T/b-fail/scripts/setup-env.sh"
printf 'echo ran-d-ok\n' > "$T/d-ok/scripts/setup-env.sh"
rc=0; N=0
chk() { # chk <설명> <기대 종료코드> <기대 문자열|-> <인자...>
  local d=$1 want=$2 pat=$3; shift 3; N=$((N+1))
  out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self "$@" 2>&1); r=$?
  if [ "$r" = "$want" ] && { [ "$pat" = - ] || grep -qF -- "$pat" <<<"$out"; }; then echo "  ok   $d"; else echo "  FAIL $d (rc=$r)"; echo "$out" | head -12; rc=1; fi
}
chk "--list 는 대상과 스크립트 유무만 보이고 실행하지 않는다" 0 "c-none  준비 스크립트 없음" --list
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self --list 2>&1); grep -q 'ran-' <<<"$out" && { echo "  FAIL --list 가 실행했다"; rc=1; } || echo "  ok   --list 는 실행하지 않는다"
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self --list 2>&1); grep -q '^head\b' <<<"$out" && { echo "  FAIL docs 영역(head)이 대상에 들었다"; rc=1; } || echo "  ok   python/node/library 만 대상(head·deploy 제외)"
chk "실패가 있으면 종료 코드 1" 1 "성공하지 못한 것 2개"
chk "실패한 영역 뒤의 영역도 계속 실행한다(d-ok)" 1 "ran-d-ok"
chk "요약표에 성공·실패(종료 3)·스크립트없음을 구분한다" 1 "스크립트없음"
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self 2>&1); grep -q '실패(종료 3)' <<<"$out" && grep -q 'a-ok  *성공' <<<"$out" && echo "  ok   표: a-ok 성공, b-fail 실패(종료 3)" || { echo "  FAIL 표 내용"; echo "$out"; rc=1; }
chk "성공하는 영역만 지정하면 종료 코드 0" 0 "전부 성공" a-ok d-ok
chk "지정하지 않은 영역은 실행하지 않는다" 0 - a-ok
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self a-ok 2>&1); grep -q ran-d-ok <<<"$out" && { echo "  FAIL 지정 밖 실행"; rc=1; } || echo "  ok   지정 밖 영역은 실행하지 않았다"
chk "대상이 아닌 이름은 사용 오류(2)" 2 "대상 영역이 아니다" nope
rm -rf "$T/d-ok"; chk "영역 폴더가 없으면 실패로 보고" 1 "폴더없음" d-ok
rm "$T/head/shared/areas.json"; chk "영역 목록을 읽지 못하면 실패(1)" 1 "영역 목록을 읽지 못했다"
[ $rc = 0 ] && echo "통과: prepare-areas 자체 시험" || exit 1
