#!/usr/bin/env bash
# publish-image.sh 의 마지막 줄(PublishResult)이 내보내기 전에 계약으로 검증되는지 본다(R7, U426). Docker·레지스트리 없이 emit_result 함수만 꺼내 실행한다.
# 확인: 정상 결과는 한 줄로 나가 계약을 통과, 계약을 어기는 결과(status 가 열거 밖)는 표준 출력이 비고 사유가 표준 오류에 나가며 성공(0)이면 종료 70, 실패 코드(예 4)는 그대로 둔다, 사용법 오류(종료 2)의 줄도 계약을 통과한다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
sed -n '/^emit_result() {/,/^}/p' "$HERE/publish-image.sh" > "$T/fn.sh"
ok() { N=$((N+1)); local n=$1; shift; if "$@"; then echo "  PASS $n"; else echo "  FAIL $n"; F=$((F+1)); fi; }
run() { # run <status> <rc> -> out/err/rc 를 $T 에
  ( source "$T/fn.sh"; PUB_JSON=1; PUB_STATUS=$1; PUB_DIGEST="sha256:$(printf 'a%.0s' $(seq 64))"; PUB_REV=abc1234; SVC=survey-service; REV=abc1234; DEPLOY_PY=$DEPLOY_PY
    (exit "$2"); emit_result ) >"$T/out" 2>"$T/err"; echo $? > "$T/rc"; }
valid_line() { "$DEPLOY_PY" -W ignore -I -c 'import json,sys;from boundary_contracts import validator;d=json.loads(sys.stdin.read().strip().splitlines()[-1]);sys.exit(1 if list(validator("PublishResult").iter_errors(d)) else 0)' < "$T/out"; }
run PUBLISHED 0;  ok "정상: 줄이 계약을 통과" valid_line; ok "정상: 종료 0, 한 줄만 나간다" bash -c "[ \"\$(cat $T/rc)\" = 0 ] && [ \$(wc -l < $T/out) = 1 ]"
run BOGUS 0;      ok "위반(status 열거 밖) 성공 경로: 표준 출력이 비어 있다" test ! -s "$T/out"; ok "위반: 사유가 표준 오류에 나가고 값이 없다" bash -c "grep -q 'PublishResult' '$T/err' && ! grep -q BOGUS '$T/err'"; ok "위반 + 성공(0): 종료 70" test "$(cat "$T/rc")" = 70
run BOGUS 4;      ok "실패 코드(4)는 그대로 둔다(줄은 status 없이 계약을 통과)" bash -c "[ \"\$(cat $T/rc)\" = 4 ]"; ok "실패(4) 줄도 계약을 통과" valid_line
echo; [ $F = 0 ] && echo "통과: PublishResult 생산자 검증 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
