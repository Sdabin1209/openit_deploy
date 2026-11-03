#!/usr/bin/env bash
# 규칙 D70.
# 게이트웨이 인증 자체 시험(D85, U82/ADR 0057). 사용: bash scripts/test-gateway-auth.sh
# 진짜 Caddyfile 을 띄우고 상류를 가짜로 둔다: 가짜 oauth2-proxy(쿠키 fakeauth=<계정> 으로 계정->그룹을 답한다)와 신원 머리글을 돌려주는 가짜 상류. 값은 출력하지 않는다.
# 진짜 Keycloak·oauth2-proxy 로그인은 scripts/test-idp-smoke.sh 가 본다. (Docker 필요)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
T=$(mktemp -d); export SECRETS_DIR=$T
PKI=$T/pki; mkdir -p "$PKI"; gateway_test_pki "$PKI" survey-service release-gate question-authoring ops-feedback-ingest kiosk-frontend admin-console model-registry keycloak oauth2-proxy || { echo "시험 PKI 를 만들지 못했다"; exit 1; }   # 게이트웨이는 상류를 https 로 부르므로 가짜 상류 앞에 TLS 를 붙인다(ADR 0060)
GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
NET=gwauth-net-$$; CN=gwauth-csrf-$$; CF=gwauth-fakeauth-$$; CU=gwauth-upstream-$$
cleanup() { docker rm -f $CN $CF $CU $CF-tls $CU-tls >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"; }; trap cleanup EXIT
FAILS=0; ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
ACCOUNTS=$DEPLOY_ROOT/test/gateway-oidc/accounts.test.conf
val() { docker run --rm $(gateway_test_mounts "$PKI") -e GATEWAY_HOST_NAMES -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/gateway-auth.caddy:/etc/caddy/auth.caddy:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" "$GW" caddy validate --config /etc/caddy/Caddyfile; }
# L20(ADR 0056): CSRF 허용 호스트 이름은 GATEWAY_HOSTS 에서 만든다
ok "GATEWAY_HOSTS 에서 호스트 이름 목록이 만들어진다(포트는 뗀다)" bash -c 'source "$1/scripts/lib.sh" 2>/dev/null; [ "$(GATEWAY_HOSTS="kiosk.hospital.local:8443, 10.0.0.5:443" gateway_host_names)" = "\"kiosk.hospital.local\", \"10.0.0.5\"" ]' _ "$DEPLOY_ROOT"
ok "와일드카드·따옴표가 든 이름은 거부(식을 깨뜨리지 못한다)" bash -c 'source "$1/scripts/lib.sh" 2>/dev/null; ! ( GATEWAY_HOSTS="*.x:8443" gateway_host_names ) >/dev/null 2>&1 && ! ( GATEWAY_HOSTS="a\"b:8443" gateway_host_names ) >/dev/null 2>&1' _ "$DEPLOY_ROOT"
ok "밖에서 보이는 주소는 첫 호스트 이름 + 밖에 보이는 포트(443 이면 포트 생략)" bash -c 'source "$1/scripts/lib.sh" 2>/dev/null; [ "$(GATEWAY_HOSTS="a.local:8443, b.local:8443" GATEWAY_PUBLIC_TLS_PORT=443 gateway_public_url)" = "https://a.local" ] && [ "$(GATEWAY_HOSTS="a.local:8443" GATEWAY_PUBLIC_TLS_PORT=9443 gateway_public_url)" = "https://a.local:9443" ] && [ "$(gateway_public_url)" = "https://localhost:8443" ]' _ "$DEPLOY_ROOT"
OUT=$(bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$T" 2>&1); ok "gen-secrets.sh 성공" test -s "$T/gateway-devices.caddy"
ok "출력에 비밀 값이 없다" bash -c '! grep -qE "[0-9a-f]{40}" <<<"$1"' _ "$OUT"
ok "정적 계정 파일·basic_auth 조각은 만들지 않는다(U82: 사람 인증은 OIDC)" bash -c '[ ! -e "$1/gateway-accounts.caddy" ] && ! grep -v "^[[:space:]]*#" "$2/config/Caddyfile" "$2/config/gateway-auth.caddy" | grep -q "basic_auth"' _ "$T" "$DEPLOY_ROOT"
ok "Caddyfile + 인증 조각 + 기기 조각이 caddy validate 통과" val
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add lobby-2 >/dev/null 2>&1
ok "기기 추가: 기본 시험 기기 4대(e2e, e2e-a, e2e-b, e2e-c) + 1대 = 5대, devices.caddy 에 토큰 5개, survey 기기 토큰 표에도 5줄(device_id=토큰)" bash -c '[ "$(bash $2/scripts/kiosk-add-device.sh list | wc -l)" = 5 ] && [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 5 ] && [ "$(grep -c "^[a-z0-9-]*=[0-9a-f]\{16,\}$" $1/tokens/survey-kiosk-device-tokens)" = 5 ]' _ "$T" "$DEPLOY_ROOT"
ok "기기 5대일 때도 caddy validate 통과(기기 목록은 expression 의 in [...] 이다: header 매처는 값 하나만 받는다)" val
ok "기기 파일을 지우고 sync 하면 폐기된다(토큰 4개, survey 표도 4줄)" bash -c 'rm $1/tokens/kiosk-device-lobby-2; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 4 ] && [ "$(wc -l < $1/tokens/survey-kiosk-device-tokens)" = 4 ]' _ "$T" "$DEPLOY_ROOT"
ok "잘못된 기기 ID 는 거부" bash -c '! bash $1/scripts/kiosk-add-device.sh add "Bad ID" >/dev/null 2>&1' _ "$DEPLOY_ROOT"
ok "기기가 0대여도 설정이 유효(모두 거부)" bash -c 'rm $1/tokens/kiosk-device-*; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; grep -q "expression false" $1/gateway-devices.caddy' _ "$T" "$DEPLOY_ROOT"
ok "0대일 때 caddy validate 통과" val
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add auth-1 >/dev/null 2>&1   # 인증 계약 시험(아래)이 쓸 기기 한 대. 위에서 0대로 만든 목록에 더한다
# 가짜 oauth2-proxy 와 가짜 상류를 같은 네트워크에 둔다. 상류 이름은 Caddyfile 이 부르는 서비스 이름이다
docker network create $NET >/dev/null
docker run -d --name $CF --network $NET --network-alias oauth2-proxy -e FAKE_ACCOUNTS=/accounts -v "$ACCOUNTS:/accounts:ro" -v "$DEPLOY_ROOT/test/gateway-oidc/fake-oauth2-proxy.py:/f.py:ro" "$UTIL" python /f.py >/dev/null
docker run -d --name $CU --network $NET $(for h in survey-service release-gate question-authoring ops-feedback-ingest kiosk-frontend admin-console model-registry keycloak; do echo --network-alias $h; done) -v "$DEPLOY_ROOT/test/gateway-oidc/echo-upstream.py:/e.py:ro" "$UTIL" python /e.py >/dev/null
printf '{\n\tadmin off\n\tskip_install_trust\n\tauto_https off\n}\nhttps://:443 {\n\ttls /pki/leaf.crt /pki/leaf.key\n\treverse_proxy 127.0.0.1:{$UP}\n}\n' > "$PKI/front.caddy"
for pair in "$CU:8080" "$CF:4180"; do docker run -d --name "${pair%%:*}-tls" --network "container:${pair%%:*}" -e UP="${pair##*:}" -v "$PKI/front.caddy:/etc/caddy/Caddyfile:ro" -v "$PKI:/pki:ro" "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null; done
# 교차 사이트 요청 방어(점검 M2)의 실제 동작: gateway 를 띄우고 헤더 조합별 응답을 본다. 인증이 없으면 401 이므로 "403 + 교차 출처 문구"는 이 규칙만의 응답이다. (Docker·Caddy 필요)
docker run -d --name $CN --network $NET $(gateway_test_mounts "$PKI") -e GATEWAY_HOST_NAMES -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/gateway-auth.caddy:/etc/caddy/auth.caddy:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" >/dev/null
CP=""; for i in $(seq 1 30); do CP=$(docker port $CN 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$CP" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$CP/healthz" && break; sleep 0.5; done   # port-wait: 게이트웨이 포트가 열릴 때까지만 기다린다
cs() { curl -sk -m 5 -o "$T/cs.out" -w '%{http_code}' -X "$1" "${@:3}" "https://127.0.0.1:$CP$2"; }
csrf_case() { # csrf_case <설명> <기대 코드> <교차 출처 문구 포함 여부> <메서드> <경로> [curl 인자...]
  local name=$1 want=$2 body=$3; shift 3; local code; code=$(cs "$@")
  local has=no; grep -q "교차 출처" "$T/cs.out" && has=yes
  if [ "$code" = "$want" ] && [ "$has" = "$body" ]; then echo "  PASS $name"; else echo "  FAIL $name (코드 $code, 기대 $want)"; FAILS=$((FAILS+1)); fi; }
csrf_case "Sec-Fetch-Site: cross-site 의 POST 는 403(교차 출처)" 403 yes POST /v1/activate -H "Sec-Fetch-Site: cross-site"
csrf_case "Sec-Fetch-Site: same-site 의 POST 도 403" 403 yes POST /v1/activate -H "Sec-Fetch-Site: same-site"
csrf_case "다른 Origin 의 POST 는 403" 403 yes POST /v1/approvals -H "Origin: https://evil.example"
csrf_case "다른 Origin 의 DELETE 도 403" 403 yes DELETE /v1/anything -H "Origin: https://evil.example"
csrf_case "Sec-Fetch-Site: same-origin 은 이 규칙이 막지 않는다(인증이 없어 401)" 401 no POST /v1/activate -H "Sec-Fetch-Site: same-origin"
csrf_case "Sec-Fetch-Site: none(주소창 직접 입력 등)은 막지 않는다" 401 no POST /v1/activate -H "Sec-Fetch-Site: none"
csrf_case "같은 출처 Origin 은 막지 않는다" 401 no POST /v1/activate -H "Origin: https://127.0.0.1:$CP"
csrf_case "헤더가 없는 요청(curl·서비스 간 호출·E2E)은 막지 않는다" 401 no POST /v1/activate
csrf_case "GET 은 교차 출처여도 이 규칙의 대상이 아니다" 200 no GET /healthz -H "Sec-Fetch-Site: cross-site"
# 기본 443(Host 에 포트 없음)과 명시 포트에서 브라우저의 Origin 이 규칙과 맞는지(점검 L6): 같은 출처면 막지 않고(인증 없어 401), 다른 호스트의 Origin 은 403
csrf_case "Host 에 포트가 없고 Origin 도 포트가 없으면(기본 443 형태: Host 127.0.0.1) 같은 출처" 401 no POST /v1/activate -H "Host: 127.0.0.1" -H "Origin: https://127.0.0.1"
csrf_case "Host 에 :8443 이 있고 Origin 도 :8443 이면 같은 출처" 401 no POST /v1/activate -H "Host: 127.0.0.1:8443" -H "Origin: https://127.0.0.1:8443"
csrf_case "Host 에 포트가 없는데 Origin 에 포트가 붙으면 다른 출처로 본다" 403 yes POST /v1/activate -H "Host: 127.0.0.1" -H "Origin: https://127.0.0.1:8443"
csrf_case "http:// 출처의 Origin 은 다른 출처" 403 yes POST /v1/activate -H "Host: 127.0.0.1" -H "Origin: http://127.0.0.1"
# L20(ADR 0056): 허용 출처는 GATEWAY_HOSTS(여기서는 기본 localhost, 127.0.0.1)에서 만든 호스트 이름 목록이다. 목록에 없는 호스트 이름의 Host 는 Origin 이 Host 와 같아도 403
# Caddy 는 사이트 이름에 없는 Host 를 핸들러에 보내지 않는다(빈 200). 그래서 이 이름들로는 보호 경로에 아예 닿지 못한다: 응답 본문이 비어 있어야 하고 401 도 상류 응답도 아니다
code=$(curl -sk -m 5 -X POST -o "$T/ev.out" -w '%{http_code}' -H "Host: evil.example:8443" -H "Origin: https://evil.example:8443" "https://127.0.0.1:$CP/v1/activate"); AN=$((${AN:-0}+1))
if [ ! -s "$T/ev.out" ] && [ "$code" != 401 ] && [ "$code" != 503 ]; then echo "  PASS Host 가 GATEWAY_HOSTS 에 없는 이름이면 Origin 이 Host 와 같아도 핸들러에 닿지 않는다(빈 응답 $code)"; else echo "  FAIL 목록에 없는 Host 가 핸들러에 닿았다 ($code, 본문 $(wc -c < "$T/ev.out") 바이트)"; FAILS=$((FAILS+1)); fi
csrf_case "목록의 다른 이름(localhost)도 같은 출처면 막지 않는다" 401 no POST /v1/activate -H "Host: localhost:$CP" -H "Origin: https://localhost:$CP"
csrf_case "같은 호스트의 다른 포트 Origin 은 다른 출처라 403" 403 yes POST /v1/activate -H "Origin: https://127.0.0.1:$((CP+1))"
csrf_case "Origin 대소문자·접두 변형(https://127.0.0.1.evil.example)은 403" 403 yes POST /v1/activate -H "Origin: https://127.0.0.1:$CP.evil.example"
# 경로 우회·청크 본문 회귀: 다른 Origin 의 상태 변경 요청은 경로 표기를 어떻게 바꿔도 403 이다(CSRF 규칙이 경로 매칭보다 먼저다). --path-as-is 로 요청 바이트 그대로
csrf_path() { # csrf_path <설명> <경로> [curl 인자...]
  local name=$1 path=$2; shift 2; local code; code=$(curl -sk -m 5 --path-as-is -X POST -o "$T/cp.out" -w '%{http_code}' -H "Origin: https://evil.example" "$@" "https://127.0.0.1:$CP$path")
  if [ "$code" = 403 ] && grep -q "교차 출처" "$T/cp.out"; then echo "  PASS CSRF 경로 우회: $name -> 403"; else echo "  FAIL CSRF 경로 우회: $name -> $code (다른 Origin 이 403 이 아니다)"; FAILS=$((FAILS+1)); fi; }
csrf_path "//v1/activate" //v1/activate
csrf_path "/v1//activate" /v1//activate
csrf_path "/v1%2factivate" /v1%2factivate
csrf_path "/v1/%2e%2e/v1/activate" /v1/%2e%2e/v1/activate
csrf_path "/V1/ACTIVATE" /V1/ACTIVATE
csrf_path "청크 본문(Transfer-Encoding: chunked)" /v1/activate -H "Transfer-Encoding: chunked" -d '{}'
csrf_path "청크 본문 + 경로 //" //v1/sessions -H "Transfer-Encoding: chunked" -d '{}'
# 우회 시도 회귀(요청 바이트 그대로 보내려고 --path-as-is): 인증 없이 보호 경로에 닿으면 안 된다. 상류가 없는 시험이므로 401/403/404 가 아니라 502/503/504(상류로 넘어감)나 200 이면 **우회**다
byp() { # byp <설명> <허용 코드들> <경로> [curl 인자...]
  local name=$1 allow=$2 path=$3; shift 3; local code; code=$(curl -sk -m 5 --path-as-is -o "$T/by.out" -w '%{http_code}' "$@" "https://127.0.0.1:$CP$path")
  case " $allow " in *" $code "*) echo "  PASS 우회 시도: $name -> $code";; *) echo "  FAIL 우회 시도: $name -> $code (허용 $allow; 상류로 넘어갔거나 인증 없이 통과했다 = 우회)"; FAILS=$((FAILS+1));; esac; }
byp "/staff/ 정상 경로는 로그인으로 보낸다(302)" "302" /staff/
byp "대소문자 /Staff/" "302 401 403 404" /Staff/
byp "/STAFF/" "302 401 403 404" /STAFF/
byp "//staff//" "302 401 403 404" //staff//
byp "///staff/x" "302 401 403 404" ///staff/x
byp "/staff/../staff/" "302 401 403 404" /staff/../staff/
byp "/./staff/" "302 401 403 404" /./staff/
byp "/x/../staff/" "302 401 403 404" /x/../staff/
byp "%2f 인코딩 /staff%2f" "302 401 403 404" /staff%2f
byp "%73 인코딩 /%73taff/" "302 401 403 404" /%73taff/
byp "%2e%2e 인코딩 /v1/%2e%2e/staff/" "302 401 403 404" /v1/%2e%2e/staff/
byp "%2e 인코딩 /staff/%2e/" "302 401 403 404" /staff/%2e/
byp "직원 API 대소문자 /V1/Staff/alerts" "302 401 403 404" /V1/Staff/alerts
byp "직원 API //v1//staff/alerts" "302 401 403 404" //v1//staff/alerts
byp "승인 경로 /v1/approvals 인증 없음" "302 401 403 404" /v1/approvals -X POST -d '{}'
byp "운영자 경로 /V1/Activate 대소문자" "302 401 403 404" /V1/Activate -X POST -d '{}'
byp "/admin 대소문자 /ADMIN/" "302 401 403 404" /ADMIN/
byp "/admin//" "302 401 403 404" /admin//
byp "Authorization 헤더 두 개(둘 다 틀림)" "302 401 403" /v1/staff/alerts -H "Authorization: Basic YTpi" -H "Authorization: Basic Yzpk"
byp "Authorization 두 개(Basic 과 Bearer)" "302 401 403" /v1/staff/alerts -H "Authorization: Basic YTpi" -H "Authorization: Bearer 0000"
byp "X-Openit-User 위조만(인증 없음)" "302 401 403" /v1/staff/alerts -H "X-Openit-User: staff-e2e"
byp "X-Openit-User 두 개 위조" "302 401 403" /v1/approvals -X POST -d '{}' -H "X-Openit-User: a" -H "X-Openit-User: b"
byp "메서드 오버라이드 X-HTTP-Method-Override" "302 401 403 404" /v1/activate -X POST -H "X-HTTP-Method-Override: GET"
byp "X-Method-Override 로 GET 처럼 위장한 POST" "302 401 403 404" /v1/rollback -X POST -H "X-Method-Override: GET" -d '{}'
byp "GET 에 오버라이드 헤더로 DELETE" "302 401 403 404" /v1/staff/alerts -H "X-HTTP-Method-Override: DELETE"
# 청크 본문: 인증이 먼저라 인증 없는 큰 본문은 401(본문 상한 413 은 인증 뒤라 E2E 5a 가 본다)
head -c $((9*1024*1024)) /dev/zero | tr '\0' 'x' > "$T/big.bin"
byp "청크 전송 9MiB 본문(인증 없음)" "302 401 403 404 413" /v1/approvals -X POST -H "Transfer-Encoding: chunked" --data-binary @"$T/big.bin"


# ---- 인증 계약 시험(boundary-contracts CONVENTIONS.md 6절 "401과 403"·"사람 신원과 역할"; RFC 9110 15.5.2·11.6.1, RFC 6750 3절) ----
# 자격이 없으면 401(+ WWW-Authenticate; 화면 경로는 로그인 /oauth2/start 로 302), 자격은 맞고 권한(역할)만 모자라면 403, 역할이 하나도 없으면(가입 승인 대기) 403 ACCOUNT_PENDING_APPROVAL.
# 통과한 요청은 가짜 상류가 200 과 받은 신원 머리글을 돌려준다.
AN=0
call() { # call <계정|-|bearer:<토큰>|cookie:<값>> <메서드> <경로> [curl 인자...] -> 코드를 표준 출력, 응답 머리글 $T/ah.out, 본문 $T/ab.out
  local who=$1 m=$2 path=$3 auth=(); shift 3
  case "$who" in -) ;; bearer:*) auth=(-H "Authorization: Bearer ${who#bearer:}");; cookie:*) auth=(-H "Cookie: fakeauth=${who#cookie:}");; *) auth=(-H "Cookie: fakeauth=$who");; esac
  curl -sk -m 5 -D "$T/ah.out" -o "$T/ab.out" -w '%{http_code}' -X "$m" "${auth[@]}" "$@" "https://127.0.0.1:$CP$path"; }
wa() { grep -i '^www-authenticate:' "$T/ah.out" | tr -d '\r' | head -1; }
loc() { grep -i '^location:' "$T/ah.out" | tr -d '\r' | head -1; }
chk401() { # chk401 <설명> <Bearer> <who> <메서드> <경로>: 401 + WWW-Authenticate: Bearer
  local name=$1 code h; shift 2; code=$(call "$@"); h=$(wa); AN=$((AN+1))
  if [ "$code" = 401 ] && grep -qE '^[Ww][Ww][Ww]-[Aa]uthenticate: Bearer\b' <<<"$h"; then echo "  PASS $name -> 401 + $h"; else echo "  FAIL $name -> $code, WWW-Authenticate='$h' (기대 401 + Bearer)"; FAILS=$((FAILS+1)); fi; }
chk302() { # chk302 <설명> <who> <메서드> <경로>: 화면 경로는 로그인으로 보낸다
  local name=$1 code l; shift; code=$(call "$@"); l=$(loc); AN=$((AN+1))
  if [ "$code" = 302 ] && grep -qi '^location: /oauth2/start?rd=' <<<"$l"; then echo "  PASS $name -> 302 $l"; else echo "  FAIL $name -> $code, $l (기대 302 /oauth2/start)"; FAILS=$((FAILS+1)); fi; }
chk403() { # chk403 <설명> <who> <메서드> <경로>
  local name=$1 code; shift; code=$(call "$@"); AN=$((AN+1))
  if [ "$code" = 403 ]; then echo "  PASS $name -> 403"; else echo "  FAIL $name -> $code (기대 403: 자격은 맞고 권한만 없다)"; FAILS=$((FAILS+1)); fi; }
chkpass() { # chkpass <설명> <who> <메서드> <경로>: 상류까지 전달되어 200 (가짜 상류의 응답)
  local name=$1 code; shift; code=$(call "$@"); AN=$((AN+1))
  if [ "$code" = 200 ]; then echo "  PASS $name -> 200 (인증·인가 통과, 상류에 전달)"; else echo "  FAIL $name -> $code (기대 200: 인증·권한이 맞는데 막혔다)"; FAILS=$((FAILS+1)); fi; }
echo_hdr() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]))["headers"];print(d.get(sys.argv[2],[""])[0])' "$T/ab.out" "$1"; }
chkhdr() { # chkhdr <설명> <기대 X-Openit-User> <기대 X-Openit-Roles> <who> <메서드> <경로> [curl 인자...]
  local name=$1 wu=$2 wr=$3 code u r; shift 3; code=$(call "$@"); AN=$((AN+1)); u=$(echo_hdr X-Openit-User 2>/dev/null); r=$(echo_hdr X-Openit-Roles 2>/dev/null)
  if [ "$code" = 200 ] && [ "$u" = "$wu" ] && [ "$r" = "$wr" ]; then echo "  PASS $name -> X-Openit-User=$u X-Openit-Roles=$r"; else echo "  FAIL $name -> $code user='$u' roles='$r' (기대 user='$wu' roles='$wr')"; FAILS=$((FAILS+1)); fi; }
for mp in GET:/v1/staff/alerts POST:/v1/sessions/s1/intervention GET:/v1/submissions POST:/v1/approvals GET:/v1/active-pointer GET:/v1/releases POST:/v1/activate POST:/v1/rollback GET:/v1/cases POST:/v1/cases/c1/review POST:/v1/materials GET:/v1/drafts POST:/v1/reviews GET:/v1/results GET:/v1/results/s1 POST:/v1/results/s1/ack GET:/v1/staff/push-config; do
  chk401 "자격 없음 ${mp/:/ }" Bearer - "${mp%%:*}" "${mp#*:}"; done
chk302 "자격 없음 GET /staff/ 는 로그인으로" - GET /staff/
chk302 "자격 없음 GET /admin/ 은 로그인으로" - GET /admin/
chk401 "모르는 계정(세션이 없는 쿠키) GET /v1/staff/alerts" Bearer nobody GET /v1/staff/alerts
chk401 "Bearer 토큰 한 개 GET /v1/staff/alerts (서비스 토큰은 사람 경로에서 자격이 아니다)" Bearer bearer:0000 GET /v1/staff/alerts
chk403 "staff 계정 -> operator 경로 POST /v1/activate" staff-e2e POST /v1/activate
chk403 "staff 계정 -> 승인 경로 POST /v1/approvals" staff-e2e POST /v1/approvals
chk403 "staff 계정 -> 승인 읽기 GET /v1/submissions" staff-e2e GET /v1/submissions
chk403 "staff 계정 -> 검토 경로 GET /v1/cases" staff-e2e GET /v1/cases
chk403 "staff 계정 -> 저작 경로 GET /v1/drafts" staff-e2e GET /v1/drafts
chk403 "operator 계정 -> 직원 API GET /v1/staff/alerts" operator-e2e GET /v1/staff/alerts
chk403 "operator 계정 -> 직원 개입 POST /v1/sessions/s1/intervention" operator-e2e POST /v1/sessions/s1/intervention
chk403 "operator 계정 -> 직원 화면 GET /staff/" operator-e2e GET /staff/
chk403 "reviewer 계정 -> 롤백 POST /v1/rollback" reviewer-e2e POST /v1/rollback
chk403 "trainer(release-approver) 계정 -> 검토 게시 POST /v1/cases/c1/review" trainer-e2e POST /v1/cases/c1/review
chk403 "author 계정 -> 활성화 POST /v1/activate" author-e2e POST /v1/activate
chkpass "staff 계정 -> 직원 API" staff-e2e GET /v1/staff/alerts
# U92(3.4.0): clinician 은 푸시 설정·구독 경로만 더 쓴다. 알림 목록·개입 같은 직원 API 는 계속 403
chkpass "clinician 계정 -> 푸시 설정 GET /v1/staff/push-config" clinician-e2e GET /v1/staff/push-config
chkpass "clinician 계정 -> 푸시 구독 POST /v1/staff/push-subscriptions" clinician-e2e POST /v1/staff/push-subscriptions
chkpass "clinician 계정 -> 푸시 해지 POST /v1/staff/push-subscriptions/unsubscribe" clinician-e2e POST /v1/staff/push-subscriptions/unsubscribe
up_tok() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]))["headers"];print(d.get("Authorization",[""])[0])' "$T/ab.out"; }
chkup() { # chkup <설명> <기대 상류 토큰 파일 이름> <who> <메서드> <경로>: 상류가 받은 Authorization 이 그 비밀 파일의 토큰이다
  local name=$1 want=$2 code got; shift 2; code=$(call "$@"); AN=$((AN+1)); got=$(up_tok 2>/dev/null)
  if [ "$code" = 200 ] && [ "$got" = "Bearer $(tr -d '\r\n' < "$T/tokens/$want")" ]; then echo "  PASS $name -> 상류 토큰 = $want"; else echo "  FAIL $name -> $code, 상류 토큰이 $want 가 아니다"; FAILS=$((FAILS+1)); fi; }
# D7a: survey-service 는 push 경로에서 topics results 를 result-reader 토큰 요청에만 허용한다 -> clinician 전용 계정은 result-reader, staff 도 가진 계정은 staff 토큰 + X-Openit-Roles
chkup "clinician 전용 계정의 push-config 요청: 상류 토큰 = survey-result-reader" survey-result-reader clinician-e2e GET /v1/staff/push-config
chkup "clinician 전용 계정의 push-subscriptions 요청: 상류 토큰 = survey-result-reader" survey-result-reader clinician-e2e POST /v1/staff/push-subscriptions
chkup "staff 전용 계정의 push-subscriptions 요청: 상류 토큰 = survey-api-staff" survey-api-staff staff-e2e POST /v1/staff/push-subscriptions
chkup "staff 도 가진 계정의 push 요청: staff 토큰" survey-api-staff both-e2e POST /v1/staff/push-subscriptions
chkhdr "staff 도 가진 계정: X-Openit-Roles 에 두 역할이 그대로 간다" both-e2e staff,clinician both-e2e POST /v1/staff/push-subscriptions
chk403 "clinician 계정 -> 직원 알림 목록 GET /v1/staff/alerts" clinician-e2e GET /v1/staff/alerts
chk403 "clinician 계정 -> 직원 개입 POST /v1/sessions/s1/intervention" clinician-e2e POST /v1/sessions/s1/intervention
chk403 "operator 계정 -> 푸시 설정 GET /v1/staff/push-config" operator-e2e GET /v1/staff/push-config
chkpass "staff 계정 -> 푸시 설정 GET /v1/staff/push-config" staff-e2e GET /v1/staff/push-config
chkpass "operator 계정 -> 활성화" operator-e2e POST /v1/activate
chkpass "release-approver 계정 -> 승인 결정" trainer-e2e POST /v1/approvals
chkpass "reviewer 계정 -> 검토 목록" reviewer-e2e GET /v1/cases
chkpass "author 계정 -> 저작 초안" author-e2e GET /v1/drafts
chkpass "clinical-reviewer 계정 -> 저작 초안" clinical-e2e GET /v1/drafts
chkpass "clinician 계정 -> 결과 조회 GET /v1/results" clinician-e2e GET /v1/results
chkpass "어느 역할이든 정적 승인 화면 /admin/ 은 인증과 역할만 본다(여기서는 staff 가 통과: 화면은 모든 역할)" staff-e2e GET /admin/
# 가입 승인 대기: 인증은 됐으나 역할(그룹)이 없다 -> 모든 사람 경로에서 403 ACCOUNT_PENDING_APPROVAL
chk403 "승인 대기 계정 GET /v1/staff/alerts" pending-e2e GET /v1/staff/alerts
chk403 "승인 대기 계정 GET /admin/" pending-e2e GET /admin/
AN=$((AN+1)); call pending-e2e GET /v1/submissions >/dev/null; if grep -q '"reason":"ACCOUNT_PENDING_APPROVAL"' "$T/ab.out" && grep -q '"code":"PERMISSION_DENIED"' "$T/ab.out"; then echo "  PASS 승인 대기 계정의 403 본문은 PERMISSION_DENIED / ACCOUNT_PENDING_APPROVAL"; else echo "  FAIL 승인 대기 본문: $(cat "$T/ab.out")"; FAILS=$((FAILS+1)); fi
# 신원 머리글(계약 CONVENTIONS 6절): 인증 뒤 X-Openit-User 와 X-Openit-Roles(쉼표 목록)를 붙이고, 클라이언트가 보낸 같은 이름의 머리글은 지운다
chkhdr "staff 계정: X-Openit-User=staff-e2e, X-Openit-Roles=staff" staff-e2e staff staff-e2e GET /v1/staff/alerts
chkhdr "한 사람이 역할 둘(reviewer,clinician): 쉼표 목록 그대로 전달" multi-e2e reviewer,clinician multi-e2e GET /v1/cases
chkhdr "위조한 X-Openit-User·X-Openit-Roles 는 인증 결과로 덮어쓴다" staff-e2e staff staff-e2e GET /v1/staff/alerts -H "X-Openit-User: attacker" -H "X-Openit-Roles: admin,operator"
chkhdr "위조한 X-Auth-Request-* 는 믿지 않는다(인증 결과로 덮어쓴다)" staff-e2e staff staff-e2e GET /v1/staff/alerts -H "X-Auth-Request-User: attacker" -H "X-Auth-Request-Preferred-Username: attacker" -H "X-Auth-Request-Groups: admin,operator"
chk401 "위조한 X-Auth-Request-* 만으로는 인증되지 않는다" Bearer - GET /v1/staff/alerts -H "X-Auth-Request-User: staff-e2e" -H "X-Auth-Request-Preferred-Username: staff-e2e" -H "X-Auth-Request-Groups: staff"
chkhdr "화면 경로(/admin/)에는 신원 머리글을 붙이지 않는다(정적 화면)" "" "" staff-e2e GET /admin/
# 게이트웨이 자신의 /healthz·/readyz: 상태 코드와 본문 HealthStatus(status), Content-Type json (R2.3·R5.1)
for pth in /healthz /readyz; do AN=$((AN+1)); hb=$(curl -sk -m 10 -D "$T/hh" "https://127.0.0.1:$CP$pth"); hc=$(sed -n '1s/[^ ]* \([0-9]*\).*/\1/p' "$T/hh")
  if [ "$hc" = 200 ] && echo "$hb" | grep -Eq '^\{"status": ?"ok"\}$' && grep -qi '^content-type: application/json' "$T/hh"; then echo "  PASS $pth 는 200 + {\"status\":\"ok\"} + application/json"; else echo "  FAIL $pth: $hc '$hb'"; FAILS=$((FAILS+1)); fi; done
# 본문 상한(8MiB)을 Content-Length 로 넘는 요청은 상류로 보내기 전에 413 이다(상류가 TLS 사이드카일 때 본문 읽기 오류가 503 으로 올라왔다, 4차 E2E 5a)
AN=$((AN+1)); big=$(head -c 9437184 /dev/zero | curl -sk -o /dev/null -m 30 -w '%{http_code}' -X POST --data-binary @- -H 'Content-Type: text/plain' "https://127.0.0.1:$CP/v1/materials?question_set_id=x" 2>/dev/null || true)
if [ "$big" = 413 ]; then echo "  PASS 8MiB 초과 본문은 413"; else echo "  FAIL 8MiB 초과 본문이 $big (기대 413)"; FAILS=$((FAILS+1)); fi
# E2E 와 같은 기대표·같은 스크립트(scripts/check-unauth-expectations.sh, test/gateway-oidc/unauth-expectations.txt): 인증 없는 요청의 응답
AN=$((AN+1)); if out=$(bash "$DEPLOY_ROOT/scripts/check-unauth-expectations.sh" "https://127.0.0.1:$CP" --insecure 2>&1); then echo "  PASS $out"; else echo "  FAIL 인증 없는 요청 기대표: $out"; FAILS=$((FAILS+1)); fi
# 기기 토큰 경로(공개 API): 토큰이 없거나 틀리면 401 + WWW-Authenticate: Bearer (RFC 6750 3절)
DEVTOK=$(cat "$T/tokens/kiosk-device-auth-1")
chk401 "기기 토큰 없음 POST /v1/sessions" Bearer - POST /v1/sessions
chk401 "틀린 기기 토큰 POST /v1/sessions" Bearer bearer:0000000000000000000000000000000000000000000000000000000000000000 POST /v1/sessions
chk401 "사람 세션 쿠키는 기기 경로에서 자격이 아니다(Bearer 를 안내)" Bearer staff-e2e POST /v1/sessions
chk401 "기기 토큰 없음 GET /v1/sessions/s1" Bearer - GET /v1/sessions/s1
chkpass "유효한 기기 토큰 POST /v1/sessions" bearer:"$DEVTOK" POST /v1/sessions
chk401 "기기 토큰 없음 GET /v1/question-sets (I10 문진표 목록은 세션과 같은 기기 인증)" Bearer - GET /v1/question-sets
chk401 "틀린 기기 토큰 GET /v1/question-sets" Bearer bearer:0000000000000000000000000000000000000000000000000000000000000000 GET /v1/question-sets
chkpass "유효한 기기 토큰 GET /v1/question-sets" bearer:"$DEVTOK" GET /v1/question-sets
chkpass "유효한 기기 토큰 GET /v1/question-sets?question_set_id=x (쿼리가 막히지 않는다)" bearer:"$DEVTOK" GET "/v1/question-sets?question_set_id=x"
# 기계 경로(추론 서버의 릴리스 읽기, D72): 기계 토큰만 연다. 사람 OIDC 세션은 이 경로의 자격이 아니다(D7d: 예전 `not header Authorization Basic*` 조건을 세션 쿠키 기준으로 바꿨다)
INFTOK=$(tr -d '\r\n' < "$T/tokens/gateway-inference-token")
chk401 "기계 경로 /v1/releases/r1/bundle: 쿠키도 토큰도 없으면 401 + Bearer" Bearer - GET /v1/releases/r1/bundle
chk401 "기계 경로: 틀린 기계 토큰은 401 + Bearer" Bearer bearer:0000 GET /v1/releases/r1/bundle
chk401 "기계 경로 /v1/active-pointer: 자격이 없으면 401 + Bearer(운영자 블록)" Bearer - GET /v1/active-pointer
chkup "기계 경로: 맞는 기계 토큰이면 상류에는 model-serving 읽기 토큰으로 바꿔 붙는다" gate-read-model-serving bearer:"$INFTOK" GET /v1/releases/r1/bundle
chkup "기계 경로 /v1/active-pointer: 기계 토큰이면 같은 읽기 토큰" gate-read-model-serving bearer:"$INFTOK" GET /v1/active-pointer
AN=$((AN+2))
c=$(call "trainer-e2e; _openit_session=x" GET /v1/releases/r1/bundle)   # 쿠키 머리글 값에 진짜 세션 쿠키 이름도 싣는다(가짜 인증은 fakeauth 만 읽는다)
[ "$c" = 404 ] && echo "  PASS 사람 OIDC 세션(승인자)이 기계 경로 /v1/releases/* 로 오면 404(401 도 통과도 아니다)" || { echo "  FAIL 사람 세션의 기계 경로 -> $c (기대 404)"; FAILS=$((FAILS+1)); }
c=$(call operator-e2e GET /v1/active-pointer); [ "$c" = 200 ] && echo "  PASS 사람 operator 세션의 /v1/active-pointer 는 운영자 블록으로 간다(200)" || { echo "  FAIL operator active-pointer -> $c"; FAILS=$((FAILS+1)); }
chk403 "사람 staff 세션의 /v1/active-pointer 는 403(operator 아님)" staff-e2e GET /v1/active-pointer
# 사람 인증 경로(U82): /oauth2/* 는 oauth2-proxy 로, /auth/* 는 Keycloak 으로. /oauth2/auth 와 Keycloak master realm 은 밖에 닫는다
AN=$((AN+4))
c=$(call - GET /oauth2/start); [ "$c" = 200 ] && echo "  PASS /oauth2/* 는 인증 없이 oauth2-proxy 로 간다(가짜 상류가 200)" || { echo "  FAIL /oauth2/start -> $c"; FAILS=$((FAILS+1)); }
c=$(call staff-e2e GET /oauth2/auth); [ "$c" = 404 ] && echo "  PASS /oauth2/auth 는 밖에 닫혀 있다(404)" || { echo "  FAIL /oauth2/auth -> $c"; FAILS=$((FAILS+1)); }
c=$(call - GET /auth/realms/openit/.well-known/openid-configuration); [ "$c" = 200 ] && echo "  PASS /auth/realms/openit/* 는 Keycloak 으로 간다" || { echo "  FAIL /auth/realms/openit -> $c"; FAILS=$((FAILS+1)); }
c1=$(call - GET /auth/realms/master/protocol/openid-connect/auth); c2=$(call - GET /auth/admin/master/console/); [ "$c1" = 404 ] && [ "$c2" = 404 ] && echo "  PASS Keycloak master realm 은 밖에 닫혀 있다(404)" || { echo "  FAIL master realm -> $c1 $c2"; FAILS=$((FAILS+1)); }
echo "  인증 계약 시험 ${AN}건 실행"
[ $FAILS = 0 ] && echo "통과: 게이트웨이 인증 자체 시험" || { echo "실패: $FAILS건"; exit 1; }
