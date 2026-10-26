#!/usr/bin/env bash
# publish-image.sh 의 사용법·인자 검사가 Docker 없이도 문서대로 동작하는지 확인한다(데몬 불필요, 빠름). 종료 코드: 인자 오류 2, --help 0, Docker 없음 1.
set -uo pipefail
cd "$(dirname "$0")/.."
FAILS=0; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
for c in dirname grep cat sed tr head awk; do ln -sf "$(command -v $c)" "$T/$c"; done   # docker 가 없는 PATH
chk() { local want=$1 name=$2; shift 2; env -i PATH="$T" "$(command -v bash)" scripts/publish-image.sh "$@" >"$T/out" 2>&1; local rc=$?
  if [ $rc = "$want" ]; then echo "  [PASS] $name (종료 코드 $rc)"; else echo "  [FAIL] $name: 종료 코드 $rc (기대 $want)"; FAILS=$((FAILS+1)); fi; }
chk 2 "인자 없음 -> 사용법" ;                       grep -q "영역 CI가 이미지 하나를" "$T/out" && echo "  [PASS] 사용법 첫 줄 안내(단수/복수 구분)" || { echo "  [FAIL] 사용법 첫 줄 안내"; FAILS=$((FAILS+1)); }
chk 0 "--help" --help;                              grep -q "publish-images.sh(복수)" "$T/out" && echo "  [PASS] --help 에 복수 스크립트 구분" || { echo "  [FAIL] --help 안내"; FAILS=$((FAILS+1)); }
chk 0 "-h" -h
chk 2 "인자 하나만" survey-service
chk 2 "알 수 없는 서비스 이름" no-such-service some-image
chk 2 "알 수 없는 옵션" survey-service some-image --bad
chk 1 "인자가 맞고 Docker 가 없으면 1" survey-service some-image --registry 127.0.0.1:1
echo; [ $FAILS = 0 ] && echo "test-publish-args: 전부 통과" || echo "test-publish-args: 실패 $FAILS건"
exit $([ $FAILS = 0 ] && echo 0 || echo 1)
