#!/usr/bin/env bash
# E2E·데모가 시험 도구에 내보내는 사람 화면 주소(GATEWAY_PUBLIC_URL)가 게이트웨이 HTTPS 호스트 포트를 담는지 본다(Docker 불필요).
# 3차 E2E 에서 한 줄 `export A=$B C="$(f)"` 안에서 $(f) 가 A 의 대입보다 먼저 풀려 기본 포트 8443 이 들어갔고, 사람 로그인 단계 셋이 연결 거부로 죽었다.
# 방법: 스크립트의 그 블록을 그대로 꺼내 포트를 정한 환경에서 실행하고 결과를 본다. 사용: bash scripts/test-e2e-public-url.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; F=0
chk() { # chk <설명> <스크립트> <시작 패턴> <끝 패턴>
  local name=$1 file=$2 from=$3 to=$4 blk out
  if [ -n "$to" ]; then blk=$(sed -n "/$from/,/$to/p" "$HERE/$file"); else blk=$(grep -m1 -- "$from" "$HERE/$file"); fi; [ -n "$blk" ] || { echo "  FAIL $name: 블록을 찾지 못했다($file)"; F=$((F+1)); return; }
  out=$(DEPLOY_NO_DOCKER=1 bash -c 'source "$1/lib.sh"; GATEWAY_TLS_PORT=34567; GATEWAY_HOSTS="localhost:8443, 127.0.0.1:8443"; unset GATEWAY_PUBLIC_TLS_PORT; '"$blk"'; echo "$GATEWAY_PUBLIC_URL"' _ "$HERE" 2>&1 | tail -1)
  if [ "$out" = "https://localhost:34567" ]; then echo "  PASS $name -> $out"; else echo "  FAIL $name -> '$out' (기대 https://localhost:34567)"; F=$((F+1)); fi; }
chk "e2e.sh: 밖에 보이는 주소가 게시 포트를 담는다" e2e.sh '^export GATEWAY_PUBLIC_TLS_PORT=' '^export GATEWAY_PUBLIC_URL='
chk "demo.sh: 밖에 보이는 주소가 게시 포트를 담는다" demo.sh 'export GATEWAY_TLS_PORT GATEWAY_PUBLIC_TLS_PORT=' ''
echo; [ $F = 0 ] && echo "통과: 사람 화면 주소 시험" || { echo "실패: $F건"; exit 1; }
