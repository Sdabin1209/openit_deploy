#!/usr/bin/env bash
# 키오스크 기기 인증서(mTLS) 게이트웨이 자체 시험(Docker·openssl 필요, ADR 0040). 사용: bash scripts/test-device-mtls.sh   (임시 폴더·일회용 CA·임시 네트워크, 끝나면 모두 지운다)
# 확인: Caddyfile 검증(인증서 검증 꺼짐·켜짐), 신뢰 CA 의 인증서로 키오스크 경로 통과 + CN 이 X-Openit-Device 로 전달, 위조 헤더 덮어쓰기, 인증서 없으면 401(+Bearer 안내), 다른 CA 인증서는 TLS 거부,
# 직원 경로는 인증서 없이도 계정 인증으로 동작, 2.x 기기 토큰 경로에서도 클라이언트 위조 헤더가 지워진다. 키 값은 출력하지 않는다.
set -uo pipefail
# 사용: test-device-mtls.sh [--static]   --static: Docker·Caddy 없이 하는 정적 시험만(일회용 CA 스크립트, 설정 조각, Caddyfile 구조). Docker 에 닿지 않으면 정적 시험만 하고 나머지를 '미실행'으로 알린다(통과로 세지 않는다)
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
STATIC_ONLY=0; [ "${1:-}" = --static ] && STATIC_ONLY=1
T=$(mktemp -d); chmod 755 "$T"; ID=$$; N=0; F=0
GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
NET=devmtls-net-$ID; CE=devmtls-echo-$ID; CG=devmtls-gw-$ID
cleanup() { docker rm -f $CG $CE >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"; }
trap cleanup EXIT
command -v openssl >/dev/null || { echo "openssl 이 필요하다"; exit 1; }
pass() { N=$((N+1)); echo "  PASS $1"; }; fail() { N=$((N+1)); F=$((F+1)); echo "  FAIL $1"; }
# ---- 정적 시험(Docker 불필요) ----
CF="$DEPLOY_ROOT/config/Caddyfile"
export DEVICE_PKI_DIR="$T/pki"; bash "$DEPLOY_ROOT/scripts/device-pki.sh" init >/dev/null 2>&1 && bash "$DEPLOY_ROOT/scripts/device-pki.sh" issue kiosk-lobby-1 >/dev/null 2>&1 && pass "일회용 CA·기기 인증서 발급(openssl)" || fail "device-pki 발급"
[ "$(stat -c %a "$T/pki")" = 700 ] && [ "$(stat -c %a "$T/pki/ca.key")" = 600 ] && [ "$(stat -c %a "$T/pki/kiosk-lobby-1.key")" = 600 ] && pass "폴더 700, 키 파일 600" || fail "키 파일 권한"
bash "$DEPLOY_ROOT/scripts/device-pki.sh" issue 'bad id' >/dev/null 2>&1 && fail "형식에 안 맞는 기기 ID 를 발급했다" || pass "기기 ID 형식(^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$)에 안 맞으면 발급 거부"
openssl verify -CAfile "$T/pki/ca.crt" "$T/pki/kiosk-lobby-1.crt" >/dev/null 2>&1 && openssl x509 -in "$T/pki/kiosk-lobby-1.crt" -noout -subject | grep -q 'CN *= *kiosk-lobby-1' && pass "발급한 인증서가 일회용 CA 로 검증되고 주체 CN 이 기기 ID 다" || fail "인증서 검증/CN"
git -C "$DEPLOY_ROOT" check-ignore -q state/device-pki/ca.key 2>/dev/null && pass "키 위치(state/device-pki)는 .gitignore 대상이다" || { [ ! -d "$DEPLOY_ROOT/.git" ] && [ ! -f "$DEPLOY_ROOT/.git" ] && echo "  SKIP .gitignore 확인(git 리포지토리 밖에서 실행)" || fail "state/device-pki 가 .gitignore 대상이 아니다"; }
grep -q '시험·데모 전용' "$DEPLOY_ROOT/scripts/device-pki.sh" && pass "device-pki.sh 에 운영 사용 금지 표시가 있다" || fail "운영 금지 표시"
! grep -v '^[[:space:]]*#' "$DEPLOY_ROOT/config/device-tls.caddy" | grep -q '^[[:space:]]*client_auth' && pass "기본 조각(device-tls.caddy)은 검증이 꺼져 있다(client_auth 없음)" || fail "기본 조각이 검증을 켠다"
grep -q 'mode verify_if_given' "$DEPLOY_ROOT/config/device-tls.mtls.caddy.example" && grep -q 'trusted_ca_cert_file /etc/caddy/device-ca.pem' "$DEPLOY_ROOT/config/device-tls.mtls.caddy.example" && pass "켠 조각은 신뢰 CA 파일 하나(/etc/caddy/device-ca.pem)를 쓴다" || fail "켠 조각 내용"
# Caddyfile 구조: 서비스(survey)로 가는 reverse_proxy 마다 클라이언트가 보낸 기기 헤더를 지우거나(토큰·직원 경로) 인증서 CN 으로 덮어쓴다(인증서 경로)
python3 - "$CF" <<'PY' && pass "survey-service 로 가는 reverse_proxy 모두 X-Openit-Device 를 지우거나 CN 으로 덮어쓰고, X-Openit-Dn 은 지운다" || fail "Caddyfile 헤더 처리"
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
blocks = [m.start() for m in re.finditer(r"reverse_proxy survey-service:8080 \{", t)]
assert len(blocks) == 4, f"survey 프록시 {len(blocks)}개"
for b in blocks:
    body = t[b:t.index("\n\t\t}\n", b)] if "\n\t\t}\n" in t[b:] else t[b:b+900]
    body = t[b:b+1200]
    assert "header_up -X-Openit-Dn" in body, "X-Openit-Dn 을 지우지 않는 프록시"
    assert ("header_up -X-Openit-Device" in body) or ('header_up X-Openit-Device "{re.devcn.1}"' in body), "기기 헤더 처리가 없는 프록시"
assert 'request_header X-Openit-Dn "dn={http.request.tls.client.subject}"' in t
assert "@device_cert header_regexp devcn X-Openit-Dn" in t and "{0,127}" in t
assert t.index("handle @device_cert") < t.index("handle @device_ok"), "인증서 경로가 토큰 경로보다 먼저여야 한다"
PY
if [ $STATIC_ONLY = 1 ] || ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "  미실행: Caddy 를 띄우는 시험(Caddyfile 검증, 인증서 통과·거부, CN 전달, 위조 헤더 덮어쓰기)은 Docker 에 닿지 않아 하지 않았다(통과 아님)"
  echo; [ $F = 0 ] && echo "통과(정적만): 기기 인증서 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }; exit $F
fi
DEPLOY_NO_DOCKER=0; detect_docker
S="$T/s"; bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$S" >/dev/null 2>&1 || { echo "gen-secrets 실패"; exit 1; }
bash "$DEPLOY_ROOT/scripts/device-pki.sh" gateway-config >/dev/null 2>&1
DEVICE_PKI_DIR="$T/pki2" bash "$DEPLOY_ROOT/scripts/device-pki.sh" init >/dev/null 2>&1; DEVICE_PKI_DIR="$T/pki2" bash "$DEPLOY_ROOT/scripts/device-pki.sh" issue rogue-1 >/dev/null 2>&1   # 신뢰하지 않는 다른 CA
gwrun() { # gwrun <이름> <device-tls 조각> <CA 파일> [docker 인자...]: 게이트웨이를 임시 네트워크에서 띄운다
  local name=$1 tls=$2 ca=$3; shift 3
  docker run -d --name "$name" --network $NET "$@" -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$S/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$S/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" \
    -v "$tls:/etc/caddy/device-tls.caddy:ro" -v "$ca:/etc/caddy/device-ca.pem:ro" -v "$S/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null; }
val() { docker run --rm -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$S/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$S/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$1:/etc/caddy/device-tls.caddy:ro" -v "$2:/etc/caddy/device-ca.pem:ro" -v "$S/tokens:/run/secrets:ro" "$GW" caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; }
val "$DEPLOY_ROOT/config/device-tls.caddy" "$DEPLOY_ROOT/config/device-ca.pem" && pass "Caddyfile 검증 통과(기본: 인증서 검증 꺼짐, 빈 조각)" || fail "Caddyfile 검증(기본)"
val "$T/pki/device-tls.caddy" "$T/pki/device-ca.pem" && pass "Caddyfile 검증 통과(인증서 검증 켜짐)" || fail "Caddyfile 검증(켜짐)"
docker network create $NET >/dev/null
docker run -d --name $CE --network $NET --network-alias survey-service -v "$DEPLOY_ROOT/test/device-mtls-echo.py:/echo.py:ro" "$UTIL" python /echo.py >/dev/null
gwrun $CG "$T/pki/device-tls.caddy" "$T/pki/device-ca.pem"
P=""; for i in $(seq 1 40); do P=$(docker port $CG 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$P" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$P/healthz" && break; sleep 0.5; done
[ -n "$P" ] || { echo "게이트웨이가 뜨지 않았다"; docker logs $CG 2>&1 | tail -5; exit 1; }
cv() { curl -sk -m 8 -D "$T/h.out" -o "$T/b.out" -w '%{http_code}' "$@"; }
U="https://127.0.0.1:$P"
c=$(cv --cert "$T/pki/kiosk-lobby-1.crt" --key "$T/pki/kiosk-lobby-1.key" -X POST "$U/v1/sessions"); dev=$(python3 -c 'import json;print(json.load(open("'$T'/b.out")).get("x-openit-device",""))' 2>/dev/null)
[ "$c" = 200 ] && [ "$dev" = kiosk-lobby-1 ] && pass "신뢰 CA 의 인증서 -> 키오스크 경로 통과, 서비스가 받은 X-Openit-Device=kiosk-lobby-1(CN)" || fail "인증서 통과/CN 전달 (코드 $c, 헤더 '$dev')"
c=$(cv --cert "$T/pki/kiosk-lobby-1.crt" --key "$T/pki/kiosk-lobby-1.key" -H "X-Openit-Device: attacker" -X POST "$U/v1/sessions"); dev=$(python3 -c 'import json;print(json.load(open("'$T'/b.out")).get("x-openit-device",""))' 2>/dev/null)
[ "$c" = 200 ] && [ "$dev" = kiosk-lobby-1 ] && pass "위조 X-Openit-Device: attacker 는 인증서 CN 으로 덮어쓰인다" || fail "위조 헤더 덮어쓰기 (코드 $c, 헤더 '$dev')"
c=$(cv -X POST "$U/v1/sessions"); w=$(grep -ic '^www-authenticate: bearer' "$T/h.out")
[ "$c" = 401 ] && [ "$w" = 1 ] && pass "인증서 없음 -> 401 + WWW-Authenticate: Bearer" || fail "인증서 없음 (코드 $c)"
c=$(cv -H "X-Openit-Device: attacker" -X POST "$U/v1/sessions")
[ "$c" = 401 ] && pass "인증서 없이 위조 헤더만 보내도 401" || fail "무인증서 위조 헤더 (코드 $c)"
curl -sk -m 8 --cert "$T/pki2/rogue-1.crt" --key "$T/pki2/rogue-1.key" -o /dev/null "$U/v1/sessions" -X POST; rc=$?
[ "$rc" != 0 ] && pass "신뢰하지 않는 CA 의 인증서는 TLS 에서 거부된다(curl 종료 $rc)" || fail "다른 CA 인증서가 받아들여졌다"
c=$(cv "$U/staff/"); [ "$c" = 401 ] && grep -qi '^www-authenticate: basic' "$T/h.out" && pass "직원 경로는 인증서 없이도 열려 계정 인증(Basic 401)을 요구한다" || fail "직원 경로 (코드 $c)"
TOK=$(cat "$S/tokens/kiosk-device-e2e")
c=$(cv -H "Authorization: Bearer $TOK" -H "X-Openit-Device: attacker" -X POST "$U/v1/sessions"); dev=$(python3 -c 'import json;print(json.load(open("'$T'/b.out")).get("x-openit-device","<없음>"))' 2>/dev/null)
[ "$c" = 200 ] && [ "$dev" = "<없음>" ] && pass "2.x 기기 토큰 경로: 위조 X-Openit-Device 는 지워지고 서비스에 전달되지 않는다" || fail "토큰 경로 위조 헤더 (코드 $c, 헤더 '$dev')"
echo; [ $F = 0 ] && echo "통과: 기기 인증서(mTLS) 게이트웨이 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
