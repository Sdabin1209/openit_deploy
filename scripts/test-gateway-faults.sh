#!/usr/bin/env bash
# 게이트웨이 장애·중계 단독 시험(RUNTIME.md R2.1·R3.1·R3.2·R3.3·R3.5·R3.6·R4.1, Docker 필요). 사용: bash scripts/test-gateway-faults.sh
# 진짜 config/Caddyfile 을 띄우고 상류를 제어되는 가짜(test/gateway-oidc/fault-upstream.py, 사이드카 대역의 TLS 앞단 포함)로 둔다. 환자 경로(POST /v1/sessions, 기기 토큰)로 부른다.
# 모든 단언은 상태 코드 + 본문 + 필요한 머리글을 함께 본다. 환경 변수 FAULTS_MUTATE=1 이면 일부러 Caddyfile 을 망가뜨려(503 매핑 제거) 단언이 실패하는지 확인한다(변이 확인).
# 값(토큰)은 출력하지 않는다. 느린 상류(504) 경우는 게이트웨이 상류 한도(55초)를 실제로 기다리므로 이 시험은 약 90초 걸린다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
T=$(mktemp -d); export SECRETS_DIR=$T
PKI=$T/pki; mkdir -p "$PKI"; gateway_test_pki "$PKI" survey-service release-gate question-authoring ops-feedback-ingest kiosk-frontend admin-console model-registry keycloak oauth2-proxy || { echo "시험 PKI 를 만들지 못했다"; exit 1; }
GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
ID=$$; NET=gwfault-net-$ID; CN=gwfault-gw-$ID; CF=gwfault-fakeauth-$ID; CU=gwfault-up-$ID
cleanup() { [ "${FAULTS_KEEP:-0}" = 1 ] && { echo "FAULTS_KEEP=1: 컨테이너 $CN 등을 남겼다(포트 $CP, 기기 토큰 파일 $T/tokens)"; return; }; docker rm -f $CN $CF $CU $CF-tls $CU-tls >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"; }; trap cleanup EXIT
FAILS=0; N=0
chk() { # chk <설명> <조건 명령...>
  local n=$1; shift; N=$((N+1)); if "$@" >/dev/null 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
CF_FILE=$DEPLOY_ROOT/config/Caddyfile
if [ "${FAULTS_MUTATE:-0}" = 1 ]; then   # 변이: 연결 거부를 503 이 아니라 200 으로 바꾼다. 아래 R3.1 단언이 실패해야 한다
  cp "$CF_FILE" "$T/Caddyfile.mut"; sed -i 's/respond `{"code":"UPSTREAM_UNAVAILABLE"}` 503/respond `{"code":"UPSTREAM_UNAVAILABLE"}` 200/' "$T/Caddyfile.mut"; CF_FILE=$T/Caddyfile.mut
fi
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$T" >/dev/null 2>&1; bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add faults-1 >/dev/null 2>&1
DEVTOK=$(cat "$T/tokens/kiosk-device-faults-1")
docker network create $NET >/dev/null
docker run -d --name $CF --network $NET --network-alias oauth2-proxy -e FAKE_ACCOUNTS=/accounts -v "$DEPLOY_ROOT/test/gateway-oidc/accounts.test.conf:/accounts:ro" -v "$DEPLOY_ROOT/test/gateway-oidc/fake-oauth2-proxy.py:/f.py:ro" "$UTIL" python /f.py >/dev/null
docker run -d --name $CU --network $NET $(for h in survey-service release-gate question-authoring ops-feedback-ingest kiosk-frontend admin-console model-registry keycloak; do echo --network-alias $h; done) -v "$DEPLOY_ROOT/test/gateway-oidc/fault-upstream.py:/e.py:ro" "$UTIL" python /e.py >/dev/null
printf '{\n\tadmin off\n\tskip_install_trust\n\tauto_https off\n}\nhttps://:443 {\n\ttls /pki/leaf.crt /pki/leaf.key\n\treverse_proxy 127.0.0.1:{$UP}\n}\n' > "$PKI/front.caddy"
for pair in "$CU:8080" "$CF:4180"; do docker run -d --name "${pair%%:*}-tls" --network "container:${pair%%:*}" -e UP="${pair##*:}" -v "$PKI/front.caddy:/etc/caddy/Caddyfile:ro" -v "$PKI:/pki:ro" "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null; done
docker run -d --name $CN --network $NET $(gateway_test_mounts "$PKI") -e GATEWAY_HOST_NAMES -v "$CF_FILE:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/gateway-auth.caddy:/etc/caddy/auth.caddy:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" >/dev/null
CP=""; for i in $(seq 1 40); do CP=$(docker port $CN 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$CP" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$CP/healthz" && break; sleep 0.5; done   # port-wait: 게이트웨이 포트가 열릴 때까지만 기다린다
[ -n "$CP" ] || { echo "게이트웨이가 뜨지 않았다"; docker logs $CN 2>&1 | tail -n 5; exit 1; }
URL="https://127.0.0.1:$CP/v1/sessions"
# req <fault> [추가 curl 인자...]: 상태 코드는 stdout 첫 줄, 머리글은 $T/h, 본문은 $T/b
req() { local f=$1; shift; curl -sk -m 100 -o "$T/b" -D "$T/h" -w '%{http_code}' -X POST -H "Authorization: Bearer $DEVTOK" -H "X-Fault: $f" -H 'Content-Type: application/json' -d '{"k":1}' "$@" "$URL"; }
hdr() { grep -i "^$1:" "$T/h" | head -n 1 | sed 's/^[^:]*: *//' | tr -d '\r'; }
# ---- R2.1: 앱이 낸 4xx·5xx BoundaryError 와 413 은 상태·본문·앱이 정한 머리글 그대로 ----
c=$(req err403); chk "R2.1 앱 403 BoundaryError: 상태·본문·X-Test-Custom 그대로" bash -c '[ "$1" = 403 ] && grep -q "\"code\": \"PERMISSION_DENIED\"" "$2/b" && [ "$(grep -i "^x-test-custom:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = v-403 ]' _ "$c" "$T"
c=$(req err500); chk "R2.1 앱 500 BoundaryError 는 503 으로 바뀌지 않고 그대로" bash -c '[ "$1" = 500 ] && grep -q "\"code\": \"INTERNAL\"" "$2/b" && [ "$(grep -i "^x-test-custom:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = v-500 ]' _ "$c" "$T"
c=$(req err503); chk "R2.1 앱이 직접 낸 503 UNAVAILABLE 은 본문·Retry-After(3) 그대로(게이트웨이 UPSTREAM_UNAVAILABLE 로 덮이지 않는다)" bash -c '[ "$1" = 503 ] && grep -q "\"code\": \"UNAVAILABLE\"" "$2/b" && ! grep -q UPSTREAM_UNAVAILABLE "$2/b"' _ "$c" "$T"
chk "R2.1 앱 503 의 Retry-After 가 앱 값(3)" bash -c '[ "$(grep -i "^retry-after:" "$1/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = 3 ]' _ "$T"
c=$(req err413); chk "R2.1 앱이 낸 413 은 그대로(상태·본문 INVALID_RECORD)" bash -c '[ "$1" = 413 ] && grep -q "\"code\": \"INVALID_RECORD\"" "$2/b"' _ "$c" "$T"
c=$(req ok); chk "R2.1 정상 200 본문·X-Test-Custom 그대로" bash -c '[ "$1" = 200 ] && grep -q "\"mode\": \"ok\"" "$2/b" && [ "$(grep -i "^x-test-custom:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = v-ok ]' _ "$c" "$T"
# ---- R2.1(개정): 앱이 정한 Cache-Control·보안 머리글은 그대로, 앱이 안 정한 것만 게이트웨이가 더한다(우선순위: 앱 > 게이트웨이 선언값) ----
c=$(req app-headers); chk "R2.1 앱이 정한 Cache-Control(max-age=60)·X-Frame-Options(SAMEORIGIN)·Referrer-Policy(origin)가 그대로" bash -c '[ "$1" = 200 ] && [ "$(grep -i "^cache-control:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = max-age=60 ] && [ "$(grep -i "^x-frame-options:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = SAMEORIGIN ] && [ "$(grep -i "^referrer-policy:" "$2/h" | tr -d "\r" | sed "s/^[^:]*: *//")" = origin ]' _ "$c" "$T"
chk "R2.1 앱이 안 정한 보안 머리글은 게이트웨이가 더한다(X-Content-Type-Options: nosniff, Strict-Transport-Security)" bash -c 'grep -qi "^x-content-type-options: nosniff" "$1/h" && grep -qi "^strict-transport-security:" "$1/h"' _ "$T"
c=$(req ok); chk "R2.1 앱이 Cache-Control 을 안 정했으면 게이트웨이의 no-store 가 붙는다" bash -c 'grep -qi "^cache-control: no-store" "$1/h"' _ "$T"
# ---- R3.5: 본문 상한 초과 -> 413 + 본문, 503 아님 ----
c=$(head -c 9437184 /dev/zero | curl -sk -m 60 -o "$T/b" -D "$T/h" -w '%{http_code}' -X POST -H "Authorization: Bearer $DEVTOK" -H 'Content-Type: text/plain' --data-binary @- "$URL")
chk "R3.5 Content-Length 가 8MiB 초과: 413 + {\"code\":\"PAYLOAD_TOO_LARGE\"} + application/json" bash -c '[ "$1" = 413 ] && grep -q PAYLOAD_TOO_LARGE "$2/b" && grep -qi "^content-type: application/json" "$2/h"' _ "$c" "$T"
c=$(head -c 9437184 /dev/zero | curl -sk -m 60 -o "$T/b" -D "$T/h" -w '%{http_code}' -X POST -H "Authorization: Bearer $DEVTOK" -H 'Content-Type: text/plain' -H 'Transfer-Encoding: chunked' --data-binary @- "$URL")
chk "R3.5 전송 중(chunked)에 8MiB 초과: 413 (503 아님)" bash -c '[ "$1" = 413 ]' _ "$c"
# ---- R3.6: 요청 줄·헤더가 너무 큼 -> 414·431 ----
docker cp "$CN:/data/caddy/pki/authorities/local/root.crt" "$T/gw-ca.crt" >/dev/null 2>&1 || bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" "$CN" "$T/gw-ca.crt" >/dev/null 2>&1   # 게이트웨이 내부 CA 루트(공개): 검증을 끄지 않고 이 루트로 확인한다
big_req() { # big_req <header|uri>: 1.3MB 헤더 또는 요청 줄을 파이썬 소켓으로 보내(셸 인자·curl 이 응답을 못 읽는 문제 때문) 응답 상태 코드를 낸다
  python3 - "$1" "$CP" "$DEVTOK" "$T/gw-ca.crt" <<'PY'
import socket, ssl, sys
kind, port, tok, ca = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
junk = "a" * 1300000
line = "POST /v1/sessions%s HTTP/1.1" % (("?q=" + junk) if kind == "uri" else "")
extra = "X-Big: %s\r\n" % junk if kind == "header" else ""
req = ("%s\r\nHost: localhost\r\nAuthorization: Bearer %s\r\n%sContent-Length: 0\r\nConnection: close\r\n\r\n" % (line, tok, extra)).encode()
ctx = ssl.create_default_context(cafile=ca)   # 인증서 검증을 켠 채(게이트웨이 내부 CA 루트, 이름 localhost)
s = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=30), server_hostname="localhost")
try:
    s.sendall(req); data = b""
    while b"\r\n" not in data:
        d = s.recv(4096)
        if not d: break
        data += d
    print(data.split(b"\r\n")[0].decode().split(" ")[1] if data else "연결끊김")
except (ssl.SSLError, ConnectionError, OSError):
    print("연결끊김")
PY
}
c=$(big_req header); chk "R3.6 헤더 1.3MB: 431 (503·200 아님, 현재 값 $c)" bash -c '[ "$1" = 431 ]' _ "$c"
c=$(big_req uri); chk "R3.6 요청 줄(URI) 1.3MB: 414 또는 431 (현재 값 $c)" bash -c '[ "$1" = 414 ] || [ "$1" = 431 ]' _ "$c"
# ---- R3.1·R3.2 연결 거부: 상류가 닿지 않을 때 503 + UPSTREAM_UNAVAILABLE + Retry-After + application/json (504·빈 502 아님), R4.1 복구 ----
docker stop $CU-tls >/dev/null 2>&1
c=$(req ok)
chk "R3.1·R3.2 상류 멈춤: 503 + {\"code\":\"UPSTREAM_UNAVAILABLE\"}" bash -c '[ "$1" = 503 ] && grep -q "\"code\":\"UPSTREAM_UNAVAILABLE\"" "$2/b"' _ "$c" "$T"
chk "R3.1·R3.2 상류 멈춤: Retry-After 와 application/json 머리글" bash -c 'grep -qi "^retry-after: [0-9]" "$1/h" && grep -qi "^content-type: application/json" "$1/h"' _ "$T"
chk "R3.1·R3.2 본문에 상류 주소·내부 문구가 없다" bash -c '! grep -Eqi "survey-service|dial|tcp|lookup|connection refused|127\.0\.0\.1" "$1/b"' _ "$T"
docker start $CU-tls >/dev/null 2>&1; t0=$SECONDS; ra=$(hdr Retry-After); okc=000
for i in $(seq 1 30); do okc=$(req ok); [ "$okc" = 200 ] && break; sleep 0.5; done
chk "R4.1 상류가 돌아오면 같은 주소로 다시 200 (복구까지 $((SECONDS-t0))초, Retry-After ${ra:-?}초 이내)" bash -c '[ "$1" = 200 ] && [ "$2" -le "${3:-2}" ]' _ "$okc" "$((SECONDS-t0))" "${ra:-2}"
# ---- R3.3: 상류 한도 안에 답이 없으면 504 + UPSTREAM_UNAVAILABLE ----
LIM=$(grep -oE 'response_header_timeout 55s' "$CF_FILE" | head -n 1 | grep -oE '[0-9]+')
c=$(req sleep -H 'X-Sleep: 80')
chk "R3.3 상류 무응답: 504 + {\"code\":\"UPSTREAM_UNAVAILABLE\"} + Retry-After" bash -c '[ "$1" = 504 ] && grep -q "\"code\":\"UPSTREAM_UNAVAILABLE\"" "$2/b" && grep -qi "^retry-after: [0-9]" "$2/h"' _ "$c" "$T"
echo; [ $FAILS = 0 ] && echo "통과: 게이트웨이 장애·중계 시험 ${N}건" || { echo "실패: ${FAILS}건 / ${N}건"; exit 1; }
