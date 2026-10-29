#!/usr/bin/env bash
# 게이트웨이 인증 비밀 자체 시험(D85). 사용: bash scripts/test-gateway-auth.sh   (임시 폴더에 만들고 caddy validate 로 설정을 확인한다. 값은 출력하지 않는다)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; export SECRETS_DIR=$T
GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
FAILS=0; ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
val() { docker run --rm -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$T/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" "$GW" caddy validate --config /etc/caddy/Caddyfile; }
OUT=$(bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$T" 2>&1); ok "gen-secrets.sh 성공" test -s "$T/gateway-accounts.caddy"
ok "출력에 암호·해시·토큰 값이 없다" bash -c '! grep -qE "[0-9a-f]{40}|\$2[aby]\$" <<<"$1"' _ "$OUT"
ok "계정마다 암호·해시 파일(호스트 전용이라 모드 600, adr/0022)" bash -c 'for a in staff-e2e operator-e2e trainer-e2e reviewer-e2e; do for k in password hash; do [ "$(stat -c %a $1/tokens/account-$a-$k)" = 600 ] || exit 1; done; done' _ "$T"
ok "accounts.caddy 에 암호 평문이 없고 해시만 있다" bash -c '! grep -qF "$(cat $1/tokens/account-staff-e2e-password)" $1/gateway-accounts.caddy && grep -qF "\$2a\$" $1/gateway-accounts.caddy' _ "$T"
ok "역할 매핑: operator-e2e 는 @role_operator 에만" bash -c 'grep -q "@role_operator .*\"operator-e2e\"" $1/gateway-accounts.caddy && ! grep "@role_staff" $1/gateway-accounts.caddy | grep -q operator-e2e' _ "$T"
ok "다시 실행해도 암호·해시가 안 바뀐다(멱등)" bash -c 'a=$(cat $1/tokens/account-staff-e2e-hash); bash $2/scripts/gen-secrets.sh --test-fixtures $1 >/dev/null 2>&1; [ "$a" = "$(cat $1/tokens/account-staff-e2e-hash)" ]' _ "$T" "$DEPLOY_ROOT"
ok "Caddyfile + 생성 조각이 caddy validate 통과" val
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add lobby-2 >/dev/null 2>&1
ok "기기 추가: 기본 시험 기기 4대(e2e, e2e-a, e2e-b, e2e-c) + 1대 = 5대, devices.caddy 에 토큰 5개, survey 기기 토큰 표에도 5줄(device_id=토큰)" bash -c '[ "$(bash $2/scripts/kiosk-add-device.sh list | wc -l)" = 5 ] && [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 5 ] && [ "$(grep -c "^[a-z0-9-]*=[0-9a-f]\{16,\}$" $1/tokens/survey-kiosk-device-tokens)" = 5 ]' _ "$T" "$DEPLOY_ROOT"
ok "기기 5대일 때도 caddy validate 통과(기기 목록은 expression 의 in [...] 이다: header 매처는 값 하나만 받는다)" val
ok "기기 파일을 지우고 sync 하면 폐기된다(토큰 4개, survey 표도 4줄)" bash -c 'rm $1/tokens/kiosk-device-lobby-2; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 4 ] && [ "$(wc -l < $1/tokens/survey-kiosk-device-tokens)" = 4 ]' _ "$T" "$DEPLOY_ROOT"
ok "잘못된 기기 ID 는 거부" bash -c '! bash $1/scripts/kiosk-add-device.sh add "Bad ID" >/dev/null 2>&1' _ "$DEPLOY_ROOT"
ok "기기가 0대여도 설정이 유효(모두 거부)" bash -c 'rm $1/tokens/kiosk-device-*; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; grep -q "expression false" $1/gateway-devices.caddy' _ "$T" "$DEPLOY_ROOT"
ok "0대일 때 caddy validate 통과" val
# 파일로 준다(/dev/stdin 은 here-string 이 파이프일 때 읽히지 않아, 예전 시험은 "계정이 하나도 없다" 오류로 우연히 통과했다. 빈 계정 목록은 이제 오류가 아니다)
printf 'x-1 superuser $2a$14$ThFaB0RPIv4Ii/aJyV6gh.W8lng/OIREUbKeN9IcdNx5hY6xdg5Im\n' > "$T/bad-role.conf"; chmod 600 "$T/bad-role.conf"
GATEWAY_ACCOUNTS_CONF="$T/bad-role.conf" bash -c 'source "$1/scripts/lib.sh"; source "$1/scripts/gateway-lib.sh"; gw_parse_accounts' _ "$DEPLOY_ROOT" >/dev/null 2>&1 && { echo "  FAIL 모르는 역할을 받아들였다"; FAILS=$((FAILS+1)); } || echo "  PASS 모르는 역할은 거부"
# 교차 사이트 요청 방어(점검 M2)의 실제 동작: 가짜 비밀로 gateway 를 띄우고 헤더 조합별 응답을 본다. 인증이 없으면 401 이므로 "403 + 교차 출처 문구"는 이 규칙만의 응답이다. (Docker·Caddy 필요)
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add auth-1 >/dev/null 2>&1   # 인증 계약 시험(아래)이 쓸 기기 한 대. 위에서 0대로 만든 목록에 더한다
CN=gwauth-csrf-$$; docker rm -f $CN >/dev/null 2>&1
docker run -d --name $CN -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$T/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null 2>&1
CP=""; for i in $(seq 1 30); do CP=$(docker port $CN 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$CP" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$CP/healthz" && break; sleep 0.5; done
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
# 우회 시도 회귀(요청 바이트 그대로 보내려고 --path-as-is): 인증 없이 보호 경로에 닿으면 안 된다. 상류가 없는 시험이므로 401/403/404 가 아니라 502/503/504(상류로 넘어감)나 200 이면 **우회**다
byp() { # byp <설명> <허용 코드들> <경로> [curl 인자...]
  local name=$1 allow=$2 path=$3; shift 3; local code; code=$(curl -sk -m 5 --path-as-is -o "$T/by.out" -w '%{http_code}' "$@" "https://127.0.0.1:$CP$path")
  case " $allow " in *" $code "*) echo "  PASS 우회 시도: $name -> $code";; *) echo "  FAIL 우회 시도: $name -> $code (허용 $allow; 상류로 넘어갔거나 인증 없이 통과했다 = 우회)"; FAILS=$((FAILS+1));; esac; }
byp "/staff/ 정상 경로는 인증 요구" "401" /staff/
byp "대소문자 /Staff/" "401 403 404" /Staff/
byp "/STAFF/" "401 403 404" /STAFF/
byp "//staff//" "401 403 404" //staff//
byp "///staff/x" "401 403 404" ///staff/x
byp "/staff/../staff/" "401 403 404" /staff/../staff/
byp "/./staff/" "401 403 404" /./staff/
byp "/x/../staff/" "401 403 404" /x/../staff/
byp "%2f 인코딩 /staff%2f" "401 403 404" /staff%2f
byp "%73 인코딩 /%73taff/" "401 403 404" /%73taff/
byp "%2e%2e 인코딩 /v1/%2e%2e/staff/" "401 403 404" /v1/%2e%2e/staff/
byp "%2e 인코딩 /staff/%2e/" "401 403 404" /staff/%2e/
byp "직원 API 대소문자 /V1/Staff/alerts" "401 403 404" /V1/Staff/alerts
byp "직원 API //v1//staff/alerts" "401 403 404" //v1//staff/alerts
byp "승인 경로 /v1/approvals 인증 없음" "401 403 404" /v1/approvals -X POST -d '{}'
byp "운영자 경로 /V1/Activate 대소문자" "401 403 404" /V1/Activate -X POST -d '{}'
byp "/admin 대소문자 /ADMIN/" "401 403 404" /ADMIN/
byp "/admin//" "401 403 404" /admin//
byp "Authorization 헤더 두 개(둘 다 틀림)" "401 403" /v1/staff/alerts -H "Authorization: Basic YTpi" -H "Authorization: Basic Yzpk"
byp "Authorization 두 개(Basic 과 Bearer)" "401 403" /v1/staff/alerts -H "Authorization: Basic YTpi" -H "Authorization: Bearer 0000"
byp "X-Openit-User 위조만(인증 없음)" "401 403" /v1/staff/alerts -H "X-Openit-User: staff-e2e"
byp "X-Openit-User 두 개 위조" "401 403" /v1/approvals -X POST -d '{}' -H "X-Openit-User: a" -H "X-Openit-User: b"
byp "메서드 오버라이드 X-HTTP-Method-Override" "401 403 404" /v1/activate -X POST -H "X-HTTP-Method-Override: GET"
byp "X-Method-Override 로 GET 처럼 위장한 POST" "401 403 404" /v1/rollback -X POST -H "X-Method-Override: GET" -d '{}'
byp "GET 에 오버라이드 헤더로 DELETE" "401 403 404" /v1/staff/alerts -H "X-HTTP-Method-Override: DELETE"
# 청크 본문: 인증이 먼저라 인증 없는 큰 본문은 401(본문 상한 413 은 인증 뒤라 E2E 5a 가 본다)
head -c $((9*1024*1024)) /dev/zero | tr '\0' 'x' > "$T/big.bin"
byp "청크 전송 9MiB 본문(인증 없음)" "401 403 404 413" /v1/approvals -X POST -H "Transfer-Encoding: chunked" --data-binary @"$T/big.bin"

# ---- 인증 계약 시험(boundary-contracts CONVENTIONS.md 6절 "401과 403"; RFC 9110 15.5.2·11.6.1, RFC 6750 3절, RFC 7617) ----
# 자격이 없거나 틀리면 401 + WWW-Authenticate(사람 계정 경로 = Basic realm=..., 기기 토큰 경로 = Bearer), 자격은 맞고 권한(역할)만 모자라면 403.
# 상류가 없는 시험이라 인증·인가를 통과한 요청은 503/504(UPSTREAM_UNAVAILABLE)가 된다: 401/403 이 아니면 "통과"로 본다.
AN=0
pw() { cat "$T/tokens/account-$1-password"; }
call() { # call <기본 인증 계정|-|bearer:<토큰>|raw:<헤더 값>> <메서드> <경로>  -> 코드를 표준 출력, 응답 헤더를 $T/ah.out
  local who=$1 m=$2 path=$3 auth=()
  case "$who" in -) ;; bearer:*) auth=(-H "Authorization: Bearer ${who#bearer:}");; raw:*) auth=(-H "Authorization: ${who#raw:}");; *) auth=(-u "$who:$(pw "$who")");; esac
  curl -sk -m 5 -D "$T/ah.out" -o /dev/null -w '%{http_code}' -X "$m" "${auth[@]}" "https://127.0.0.1:$CP$path"; }
wa() { grep -i '^www-authenticate:' "$T/ah.out" | tr -d '\r' | head -1; }
chk401() { # chk401 <설명> <Basic|Bearer> <who> <메서드> <경로>
  local name=$1 scheme=$2 code h; shift 2; code=$(call "$@"); h=$(wa); AN=$((AN+1))
  case "$scheme" in Basic) pat='^[Ww][Ww][Ww]-[Aa]uthenticate: Basic realm="[^"]+"';; Bearer) pat='^[Ww][Ww][Ww]-[Aa]uthenticate: Bearer\b';; esac
  if [ "$code" = 401 ] && grep -qE "$pat" <<<"$h"; then echo "  PASS $name -> 401 + $h"; else echo "  FAIL $name -> $code, WWW-Authenticate='$h' (기대 401 + $scheme)"; FAILS=$((FAILS+1)); fi; }
chk403() { # chk403 <설명> <who> <메서드> <경로>
  local name=$1 code; shift; code=$(call "$@"); AN=$((AN+1))
  if [ "$code" = 403 ]; then echo "  PASS $name -> 403"; else echo "  FAIL $name -> $code (기대 403: 자격은 맞고 권한만 없다)"; FAILS=$((FAILS+1)); fi; }
chkpass() { # chkpass <설명> <who> <메서드> <경로>: 401/403 이 아니어야 한다(상류가 없어 503/504)
  local name=$1 code; shift; code=$(call "$@"); AN=$((AN+1))
  case "$code" in 401|403) echo "  FAIL $name -> $code (인증·권한이 맞는데 막혔다)"; FAILS=$((FAILS+1));; *) echo "  PASS $name -> $code (인증·인가 통과)";; esac; }
BASIC_PATHS="GET:/staff/ GET:/admin/ GET:/v1/staff/alerts POST:/v1/sessions/s1/intervention GET:/v1/submissions POST:/v1/approvals GET:/v1/active-pointer GET:/v1/releases POST:/v1/activate POST:/v1/rollback GET:/v1/cases POST:/v1/cases/c1/review POST:/v1/materials GET:/v1/drafts POST:/v1/reviews"
for mp in $BASIC_PATHS; do chk401 "자격 없음 ${mp/:/ }" Basic - "${mp%%:*}" "${mp#*:}"; done
chk401 "틀린 암호 GET /v1/staff/alerts" Basic raw:"Basic $(printf 'staff-e2e:wrong-password' | base64 -w0)" GET /v1/staff/alerts
chk401 "없는 계정 GET /v1/staff/alerts" Basic raw:"Basic $(printf 'nobody:wrong-password' | base64 -w0)" GET /v1/staff/alerts
chk401 "틀린 암호 POST /v1/approvals" Basic raw:"Basic $(printf 'trainer-e2e:wrong-password' | base64 -w0)" POST /v1/approvals
chk401 "Bearer 자격은 사람 계정 경로에서 자격 없음(Basic 을 안내)" Basic raw:"Bearer 0000" GET /v1/staff/alerts
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
chkpass "operator 계정 -> 활성화" operator-e2e POST /v1/activate
chkpass "release-approver 계정 -> 승인 결정" trainer-e2e POST /v1/approvals
chkpass "reviewer 계정 -> 검토 목록" reviewer-e2e GET /v1/cases
chkpass "author 계정 -> 저작 초안" author-e2e GET /v1/drafts
chkpass "clinical-reviewer 계정 -> 저작 초안" clinical-e2e GET /v1/drafts
chkpass "어느 역할이든 정적 승인 화면 /admin/ 은 인증만 본다" staff-e2e GET /admin/
# 기기 토큰 경로(공개 API): 토큰이 없거나 틀리면 401 + WWW-Authenticate: Bearer (RFC 6750 3절)
DEVTOK=$(cat "$T/tokens/kiosk-device-auth-1")
chk401 "기기 토큰 없음 POST /v1/sessions" Bearer - POST /v1/sessions
chk401 "틀린 기기 토큰 POST /v1/sessions" Bearer bearer:0000000000000000000000000000000000000000000000000000000000000000 POST /v1/sessions
chk401 "Basic 자격은 기기 경로에서 자격 없음(Bearer 를 안내)" Bearer staff-e2e POST /v1/sessions
chk401 "기기 토큰 없음 GET /v1/sessions/s1" Bearer - GET /v1/sessions/s1
chkpass "유효한 기기 토큰 POST /v1/sessions" bearer:"$DEVTOK" POST /v1/sessions
# 사람 계정이 없는 운영 기본 구성(gen-secrets.sh 기본): 사람 경로는 모두 401 이고 Basic 을 안내해야 한다(빈 basic_auth 블록 대신 만든 인증 블록)
E=$T/empty; bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$E" >/dev/null 2>&1
CE=gwauth-empty-$$; docker rm -f $CE >/dev/null 2>&1
docker run -d --name $CE -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$E/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$E/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$E/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null 2>&1
CP_SAVE=$CP; CP=""; for i in $(seq 1 30); do CP=$(docker port $CE 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$CP" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$CP/healthz" && break; sleep 0.5; done
chk401 "계정 0개 구성: GET /v1/staff/alerts" Basic - GET /v1/staff/alerts
chk401 "계정 0개 구성: POST /v1/activate" Basic - POST /v1/activate
chk401 "계정 0개 구성: GET /admin/" Basic - GET /admin/
chk401 "기기 0대 구성: POST /v1/sessions" Bearer bearer:0000 POST /v1/sessions
docker rm -f $CE >/dev/null 2>&1; CP=$CP_SAVE
# 조직이 준 계정 파일(ADR 0039): 조직이 caddy hash-password 로 만든 해시를 secrets/staff-accounts.conf 로 주면 그 암호로 실제 로그인되고, 틀린 암호는 401, 역할 밖은 403 이다
O=$T/org; mkdir -p "$O/tokens"; chmod 700 "$O" "$O/tokens"; bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$O" >/dev/null 2>&1
ORGPW="org-test-password-$$"; ORGH=$(printf '%s\n%s\n' "$ORGPW" "$ORGPW" | docker run --rm -i "$GW" caddy hash-password 2>/dev/null | tail -1 | tr -d '\r\n')
( umask 077; printf 'kim.staff staff %s\nlee.op operator %s\n' "$ORGH" "$ORGH" > "$O/staff-accounts.conf" )
SECRETS_DIR="$O" bash "$DEPLOY_ROOT/scripts/apply-accounts.sh" >/dev/null 2>&1
CO=gwauth-org-$$; docker rm -f $CO >/dev/null 2>&1
docker run -d --name $CO -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$O/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$O/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$O/tokens:/run/secrets:ro" -p 127.0.0.1::8443 "$GW" caddy run --config /etc/caddy/Caddyfile >/dev/null
CP_SAVE=$CP; CP=""; for i in $(seq 1 30); do CP=$(docker port $CO 8443/tcp 2>/dev/null | head -1 | sed 's/.*://'); [ -n "$CP" ] && curl -sk -o /dev/null -m 2 "https://127.0.0.1:$CP/healthz" && break; sleep 0.5; done
orgcall() { curl -sk -m 5 -o /dev/null -w '%{http_code}' -u "$1:$2" -X "$3" "https://127.0.0.1:$CP$4"; }
AN=$((AN+4))
c=$(orgcall kim.staff "$ORGPW" GET /v1/staff/alerts); case "$c" in 401|403) echo "  FAIL 조직이 준 해시의 암호로 로그인 -> $c"; FAILS=$((FAILS+1));; *) echo "  PASS 조직이 준 해시의 암호로 로그인 -> $c (인증·인가 통과)";; esac
c=$(orgcall kim.staff wrong-password GET /v1/staff/alerts); [ "$c" = 401 ] && echo "  PASS 틀린 암호 -> 401" || { echo "  FAIL 틀린 암호 -> $c"; FAILS=$((FAILS+1)); }
c=$(orgcall kim.staff "$ORGPW" POST /v1/activate); [ "$c" = 403 ] && echo "  PASS 역할 밖(staff -> operator 경로) -> 403" || { echo "  FAIL 역할 밖 -> $c"; FAILS=$((FAILS+1)); }
c=$(orgcall lee.op "$ORGPW" POST /v1/activate); case "$c" in 401|403) echo "  FAIL operator 계정 -> $c"; FAILS=$((FAILS+1));; *) echo "  PASS operator 계정 -> $c (인증·인가 통과)";; esac
docker rm -f $CO >/dev/null 2>&1; CP=$CP_SAVE
echo "  인증 계약 시험 ${AN}건 실행"
docker rm -f $CN >/dev/null 2>&1
[ $FAILS = 0 ] && echo "통과: 게이트웨이 인증 자체 시험" || { echo "실패: $FAILS건"; exit 1; }
