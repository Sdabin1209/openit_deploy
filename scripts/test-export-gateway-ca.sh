#!/usr/bin/env bash
# export-gateway-ca.sh 단독 시험(Docker 필요): 공개 입구의 출력 마운트 볼륨(<프로젝트>_gateway-root)에서 root_ca.crt 를 읽는다. 인증서면 쓰고(모드 644), 인증서가 아니거나 파일이 없으면 실패한다. 이미지 부명령은 부르지 않는다.
# 임시 볼륨 1개·컨테이너 1개를 만들고 이름으로 지운다. 사용: bash scripts/test-export-gateway-ca.sh
set -uo pipefail
source "$(dirname "$0")/lib.sh"; detect_docker
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); ID=$$; P=xgc$ID; WD="$DEPLOY_ROOT/build/logs/xgc-$ID"
cleanup() { "$DOCKER" rm -f "$P-gateway-1" >/dev/null 2>&1; "$DOCKER" volume rm "${P}_gateway-root" >/dev/null 2>&1; rm -rf "$WD"; }; trap cleanup EXIT
mkdir -p "$WD"; chmod 777 "$WD"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$WD/k.pem" -out "$WD/root_ca.crt" -days 1 -subj /CN=test-root >/dev/null 2>&1 || { echo "openssl 이 없다"; exit 77; }
"$DOCKER" volume create "${P}_gateway-root" >/dev/null; "$DOCKER" run -d --name "$P-gateway-1" "$UTIL" sleep 300 >/dev/null
put() { "$DOCKER" run --rm -v "${P}_gateway-root:/o" -v "$WD:/w:ro" --user 0:0 "$UTIL" sh -c "$1" >/dev/null; }
F=0; chk() { local n=$1 want=$2; shift 2; "$@" >"$WD/out.txt" 2>&1; local rc=$?; if [ "$rc" = "$want" ]; then echo "  PASS $n"; else echo "  FAIL $n (rc=$rc, 기대 $want)"; sed 's/^/     /' "$WD/out.txt" | head -5; F=$((F+1)); fi; }
chk "파일이 없으면 실패" 1 bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$P" --retries 1 "$WD/out.crt"
put "echo not-a-cert > /o/root_ca.crt"
chk "인증서 형식이 아니면 실패" 1 bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$P" --retries 1 "$WD/out.crt"
put "cp /w/root_ca.crt /o/root_ca.crt"
chk "인증서면 쓴다" 0 bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$P" --retries 3 "$WD/out.crt"
cmp -s "$WD/root_ca.crt" "$WD/out.crt" && [ "$(stat -c %a "$WD/out.crt")" = 644 ] && echo "  PASS 내용 일치, 모드 644" || { echo "  FAIL 내용·모드"; F=$((F+1)); }
grep -q 'export-root' "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" && grep -v '^#' "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" | grep -q 'export-root' && { echo "  FAIL 이미지 부명령 호출이 남았다"; F=$((F+1)); } || echo "  PASS 이미지 부명령 호출 없음"
[ $F = 0 ] && echo "통과: export-gateway-ca 시험" || { echo "실패: $F건"; exit 1; }
