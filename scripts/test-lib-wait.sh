#!/usr/bin/env bash
# lib.sh 의 공용 함수 시험(Docker 불필요): wait_ready, lock_set, gen_stack_files 의 compose 실패 처리. 변이 두 개(105 행 실패 처리 제거, wait_ready 의 실패 반환 제거)가 시험을 깨뜨리는지도 본다.
# 우리 코드만 본다: 실제 시간 측정은 하지 않는다(상한 1~2초의 호출이 상한 안에 끝나는지만 본다).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W=$(mktemp -d "${TMPDIR:-/tmp}/test-lib-wait.XXXXXX"); trap 'rm -rf "$W"' EXIT
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
# lib.sh 사본(변이용)을 같은 폴더 구조에서 읽도록 scripts/ 안에 임시로 둔다
run_lib() { # run_lib <lib 파일> <본문>: 서브셸에서 lib 를 source 하고 본문을 돈다
  ( DEPLOY_NO_DOCKER=1; source "$1"; eval "$2" )
}
LIB="$HERE/lib.sh"

echo "== wait_ready"
run_lib "$LIB" 'wait_ready "즉시 성공" 3 true' >/dev/null 2>&1 && ok "성공하는 명령은 return 0" || ng "성공하는 명령이 실패로 끝났다"
run_lib "$LIB" 'n=0; f() { n=$((n+1)); [ -f '"$W"'/go ]; }; ( sleep 2; touch '"$W"'/go ) & wait_ready "늦게 준비" 10 f' >/dev/null 2>&1 && ok "늦게 준비되는 명령을 기다려 return 0" || ng "늦게 준비되는 명령을 기다리지 못했다"
rm -f "$W/go"
err=$(run_lib "$LIB" 'f() { echo "마지막-출력-표지"; return 1; }; wait_ready "실패 설명 표지" 1 f' 2>&1 >/dev/null); rc=$?
[ $rc = 1 ] && ok "상한을 넘으면 return 1" || ng "상한을 넘었는데 return $rc"
case "$err" in *"실패 설명 표지"*"마지막-출력-표지"*) ok "설명과 마지막 출력을 남긴다";; *) ng "설명/마지막 출력이 없다: $err";; esac
# 변이: wait_ready 가 실패해도 0 을 돌려주면 위 시험이 실패해야 한다
python3 - "$LIB" "$HERE/.lib.mut-wait-$$.sh" <<'PY'
import sys
s=open(sys.argv[1]).read()
a=s.index('wait_ready() {'); b=s.index('\n}\n', a)
body=s[a:b]; assert body.rstrip().endswith('return 1'); body=body.rstrip()[:-len('return 1')]+'return 0'
open(sys.argv[2],'w').write(s[:a]+body+s[b:])
PY
MUT="$HERE/.lib.mut-wait-$$.sh"
run_lib "$MUT" 'wait_ready "x" 1 false' >/dev/null 2>&1 && ok "변이 확인: 실패 반환을 빼면 wait_ready 시험이 잡는다(변이는 실패를 0 으로 숨김)" || ng "변이가 걸러지지 않았다"
rm -f "$MUT"

echo "== gen_stack_files: compose 해석 실패 처리(lib.sh 105 행 변이)"
mkdir -p "$W/bin"; printf '#!/bin/sh\ntouch "%s/generator-ran"\nexit 0\n' "$W" > "$W/bin/py"; chmod +x "$W/bin/py"
BODY='DEPLOY_PY='"$W"'/bin/py; jobs_overlay_path() { echo '"$W"'/overlay.yaml; }; dc() { return 1; }; gen_stack_files t'
rm -f "$W/generator-ran"; run_lib "$LIB" "$BODY" >/dev/null 2>&1; rc=$?
if [ $rc != 0 ] && [ ! -e "$W/generator-ran" ]; then ok "dc config 가 실패하면 return 1 이고 생성기를 돌리지 않는다"; else ng "dc 실패인데 rc=$rc, 생성기 실행=$([ -e "$W/generator-ran" ] && echo 예 || echo 아니오)"; fi
MUT="$HERE/.lib.mut-105-$$.sh"
python3 - "$LIB" "$MUT" <<'PY'
import sys
s=open(sys.argv[1]).read()
t=' --format json > "$cfg" || { rm -f "$cfg"; return 1; }'
assert t in s; open(sys.argv[2],'w').write(s.replace(t,' --format json > "$cfg"'))
PY
rm -f "$W/generator-ran"; run_lib "$MUT" "$BODY" >/dev/null 2>&1
[ -e "$W/generator-ran" ] && ok "변이 확인: 실패 처리를 빼면 dc 실패 뒤에도 생성기가 돈다(시험이 잡는다)" || ng "변이가 시험에 걸리지 않았다"
rm -f "$MUT"

echo "== lock_set"
L="$W/images.lock"; printf '# 머리\nGATEWAY_IMAGE=x@sha256:1\n' > "$L"
run_lib "$LIB" "lock_set $L survey-service sha256:aa rev1111" ; rc=$?
[ $rc = 0 ] && grep -q '^SURVEY_SERVICE_DIGEST=sha256:aa$' "$L" && grep -q '^GATEWAY_IMAGE=' "$L" && ok "기록: 서비스 줄 추가, 외부 이미지 줄 유지" || ng "기록 실패 rc=$rc"
run_lib "$LIB" "lock_set $L survey-service sha256:aa rev1111"; [ $? = 3 ] && ok "같은 값이면 return 3(변경 없음)" || ng "같은 값인데 3 이 아니다"
n=$(ls "$W/history" | wc -l)
run_lib "$LIB" "lock_set $L survey-service sha256:bb rev2222 ops-feedback sha256:cc rev3333"; rc=$?
[ $rc = 0 ] && grep -q '^SURVEY_SERVICE_DIGEST=sha256:bb$' "$L" && grep -q '^OPS_FEEDBACK_REVISION=rev3333$' "$L" && [ "$(ls "$W/history" | wc -l)" = $((n+1)) ] && ok "여러 서비스를 한 번에 기록하고 이전 잠금을 history 에 남긴다" || ng "복수 기록 실패 rc=$rc"
[ "$(grep -v '^#' "$L" | sort)" = "$(grep -v '^#' "$L")" ] && ok "KEY=value 줄이 정렬되어 있다" || ng "정렬되지 않았다"

echo; if [ "$FAILS" = 0 ]; then echo "test-lib-wait: 전부 통과"; else echo "test-lib-wait: 실패 $FAILS건"; fi
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
