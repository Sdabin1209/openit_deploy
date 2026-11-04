#!/usr/bin/env bash
# client-probe.sh 단독 시험(Docker 필요): 같은 망의 서버는 ok, 다른 망의 서버는 unreachable, 없는 출발 컨테이너는 3, 그리고 변이(망을 안 붙이면 같은 망 서버도 unreachable)가 잡힌다.
# 임시 망 2개·컨테이너 3개를 만들고 끝나면 이름으로 지운다. 사용: bash scripts/test-client-probe.sh
set -uo pipefail
source "$(dirname "$0")/lib.sh"; detect_docker
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); ID=$$
NA=cprobe-a-$ID; NB=cprobe-b-$ID; SRC=cprobe-src-$ID; SRV=cprobe-srv-$ID; OTH=cprobe-oth-$ID; WD=$DEPLOY_ROOT/build/logs/cprobe-$ID
cleanup() { "$DOCKER" rm -f "$SRC" "$SRV" "$OTH" >/dev/null 2>&1; "$DOCKER" network rm "$NA" "$NB" >/dev/null 2>&1; rm -f "$WD/ca.crt" "$WD/www/healthz"; rmdir "$WD/www" "$WD" 2>/dev/null; }; trap cleanup EXIT
mkdir -p "$WD/www"; : > "$WD/ca.crt"; printf 'ok' > "$WD/www/healthz"; chmod -R a+rX "$WD"
"$DOCKER" network create "$NA" >/dev/null && "$DOCKER" network create "$NB" >/dev/null || { echo "망을 만들지 못했다"; exit 1; }
"$DOCKER" run -d --name "$SRV" --network "$NA" --network-alias srv -v "$WD/www:/www:ro" "$UTIL" python -m http.server 80 -d /www >/dev/null
"$DOCKER" run -d --name "$SRC" --network "$NA" "$UTIL" sleep 120 >/dev/null
"$DOCKER" run -d --name "$OTH" --network "$NB" "$UTIL" sleep 120 >/dev/null
for i in $(seq 1 20); do bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$SRC" "$WD/ca.crt" http http://srv/healthz 2 2>/dev/null | grep -q ok && break; sleep 1; done
F=0; chk() { local n=$1 want=$2; shift 2; local got; got=$("$@" 2>/dev/null); if [ "$got" = "$want" ]; then echo "  PASS $n"; else echo "  FAIL $n (got '$got', want '$want')"; F=$((F+1)); fi; }
chk "같은 망 서버는 ok" ok bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$SRC" "$WD/ca.crt" http http://srv/healthz 3
chk "다른 망에서는 unreachable" unreachable bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$OTH" "$WD/ca.crt" http http://srv/healthz 3
chk "TCP 도 같은 규칙" ok bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$SRC" "$WD/ca.crt" tcp srv 80 3
chk "code 모드는 상태와 본문" "200 ok" bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$SRC" "$WD/ca.crt" code http://srv/healthz
bash "$DEPLOY_ROOT/scripts/client-probe.sh" cprobe-none-$ID "$WD/ca.crt" tcp srv 80 1 >/dev/null 2>&1; rc=$?; if [ $rc = 3 ]; then echo "  PASS 없는 출발 컨테이너는 종료 3"; else echo "  FAIL 없는 출발 컨테이너 rc=$rc"; F=$((F+1)); fi
# 변이: 출발 컨테이너의 망을 읽지 않고 기본 망에 붙이면 같은 망 서버도 unreachable 이 되어 '같은 망' 시험이 잡는다
sed 's/--network "\$first"/--network bridge/' "$DEPLOY_ROOT/scripts/client-probe.sh" > "$WD/mut.sh"; sed -i "s#source \"\$(dirname \"\$0\")/lib.sh\"#source \"$DEPLOY_ROOT/scripts/lib.sh\"#; s#\$DEPLOY_ROOT/scripts/e2e_probe.py#$DEPLOY_ROOT/scripts/e2e_probe.py#" "$WD/mut.sh"
chk "변이(망을 안 붙임)는 같은 망 서버를 못 본다" unreachable bash "$WD/mut.sh" "$SRC" "$WD/ca.crt" http http://srv/healthz 3; rm -f "$WD/mut.sh"
[ $F = 0 ] && echo "통과: client-probe 시험" || { echo "실패: $F건"; exit 1; }
