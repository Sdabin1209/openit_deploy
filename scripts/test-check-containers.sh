#!/usr/bin/env bash
# check-containers.sh 자체 시험: 강화된 컨테이너는 통과, 일부러 약한 컨테이너는 FAIL. 사용: bash scripts/test-check-containers.sh   (임시 컨테이너 2개, 끝나면 지운다)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); ID=$$
GOOD=deploy-chk-good-$ID; BAD=deploy-chk-bad-$ID
cleanup() { "$DOCKER" rm -f "$GOOD-c" "$BAD-c" >/dev/null 2>&1; }; trap cleanup EXIT
"$DOCKER" image inspect "$UTIL" >/dev/null 2>&1 || "$DOCKER" pull -q "$UTIL" >/dev/null 2>&1 || { echo "SKIP: 유틸 이미지를 받지 못했다(확인 못 함, 통과 아님)"; exit 0; }
"$DOCKER" run -d --name "$GOOD-c" --label com.docker.compose.project=$GOOD --user 10001:10001 --read-only --cap-drop ALL --security-opt no-new-privileges:true --memory 64m --pids-limit 64 "$UTIL" sleep 120 >/dev/null
"$DOCKER" run -d --name "$BAD-c" --label com.docker.compose.project=$BAD "$UTIL" sleep 120 >/dev/null
N=0; F=0
chk() { N=$((N+1)); local name=$1 want=$2 txt=$3; shift 3; local out rc; out=$("$@" 2>&1); rc=$?; if [ $rc = "$want" ] && grep -qF -- "$txt" <<<"$out"; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want)"; echo "$out" | sed 's/^/       /'; F=$((F+1)); fi; }
chk "강화된 컨테이너는 통과" 0 "OK   $GOOD-c" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$GOOD"
chk "root·쓰기 가능·cap 유지 컨테이너는 FAIL(1)" 1 "root 로 실행 중이다" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$BAD"
chk "쓰기 가능 루트도 잡는다" 1 "루트 파일시스템이 쓰기 가능하다" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$BAD"
chk "cap_drop ALL 아님도 잡는다" 1 "cap_drop ALL 이 아니다" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$BAD"
chk "컨테이너가 없으면 안내" 2 "점검할 컨테이너가 없다" bash "$DEPLOY_ROOT/scripts/check-containers.sh" deploy-chk-none-$ID
echo; [ $F = 0 ] && echo "통과: check-containers 자체 시험 $N건" || { echo "실패: $F건"; exit 1; }
