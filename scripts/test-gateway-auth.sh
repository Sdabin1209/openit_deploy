#!/usr/bin/env bash
# 게이트웨이 인증 비밀 자체 시험(D85). 사용: bash scripts/test-gateway-auth.sh   (임시 폴더에 만들고 caddy validate 로 설정을 확인한다. 값은 출력하지 않는다)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; export SECRETS_DIR=$T
GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
FAILS=0; ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
val() { docker run --rm -v "$DEPLOY_ROOT/config/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$T/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$T/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$T/tokens:/run/secrets:ro" "$GW" caddy validate --config /etc/caddy/Caddyfile; }
OUT=$(bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$T" 2>&1); ok "gen-secrets.sh 성공" test -s "$T/gateway-accounts.caddy"
ok "출력에 암호·해시·토큰 값이 없다" bash -c '! grep -qE "[0-9a-f]{40}|\$2[aby]\$" <<<"$1"' _ "$OUT"
ok "계정마다 암호·해시 파일(호스트 전용이라 모드 600, adr/0022)" bash -c 'for a in staff-e2e operator-e2e trainer-e2e reviewer-e2e; do for k in password hash; do [ "$(stat -c %a $1/tokens/account-$a-$k)" = 600 ] || exit 1; done; done' _ "$T"
ok "accounts.caddy 에 암호 평문이 없고 해시만 있다" bash -c '! grep -qF "$(cat $1/tokens/account-staff-e2e-password)" $1/gateway-accounts.caddy && grep -qF "\$2a\$" $1/gateway-accounts.caddy' _ "$T"
ok "역할 매핑: operator-e2e 는 @role_operator 에만" bash -c 'grep -q "@role_operator .*\"operator-e2e\"" $1/gateway-accounts.caddy && ! grep "@role_staff" $1/gateway-accounts.caddy | grep -q operator-e2e' _ "$T"
ok "다시 실행해도 암호·해시가 안 바뀐다(멱등)" bash -c 'a=$(cat $1/tokens/account-staff-e2e-hash); bash $2/scripts/gen-secrets.sh $1 >/dev/null 2>&1; [ "$a" = "$(cat $1/tokens/account-staff-e2e-hash)" ]' _ "$T" "$DEPLOY_ROOT"
ok "Caddyfile + 생성 조각이 caddy validate 통과" val
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add lobby-2 >/dev/null 2>&1
ok "기기 추가: 기본 시험 기기 4대(e2e, e2e-a, e2e-b, e2e-c) + 1대 = 5대, devices.caddy 에 토큰 5개, survey 기기 토큰 표에도 5줄(device_id=토큰)" bash -c '[ "$(bash $2/scripts/kiosk-add-device.sh list | wc -l)" = 5 ] && [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 5 ] && [ "$(grep -c "^[a-z0-9-]*=[0-9a-f]\{16,\}$" $1/tokens/survey-kiosk-device-tokens)" = 5 ]' _ "$T" "$DEPLOY_ROOT"
ok "기기 5대일 때도 caddy validate 통과(기기 목록은 expression 의 in [...] 이다: header 매처는 값 하나만 받는다)" val
ok "기기 파일을 지우고 sync 하면 폐기된다(토큰 4개, survey 표도 4줄)" bash -c 'rm $1/tokens/kiosk-device-lobby-2; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; [ "$(grep -o Bearer $1/gateway-devices.caddy | wc -l)" = 4 ] && [ "$(wc -l < $1/tokens/survey-kiosk-device-tokens)" = 4 ]' _ "$T" "$DEPLOY_ROOT"
ok "잘못된 기기 ID 는 거부" bash -c '! bash $1/scripts/kiosk-add-device.sh add "Bad ID" >/dev/null 2>&1' _ "$DEPLOY_ROOT"
ok "기기가 0대여도 설정이 유효(모두 거부)" bash -c 'rm $1/tokens/kiosk-device-*; bash $2/scripts/kiosk-add-device.sh sync >/dev/null 2>&1; grep -q "expression false" $1/gateway-devices.caddy' _ "$T" "$DEPLOY_ROOT"
ok "0대일 때 caddy validate 통과" val
GATEWAY_ACCOUNTS_CONF=/dev/stdin bash -c 'source "$1/scripts/gateway-lib.sh"; gw_parse_accounts' _ "$DEPLOY_ROOT" <<<"x-1 superuser" >/dev/null 2>&1 && { echo "  FAIL 모르는 역할을 받아들였다"; FAILS=$((FAILS+1)); } || echo "  PASS 모르는 역할은 거부"
[ $FAILS = 0 ] && echo "통과: 게이트웨이 인증 자체 시험" || { echo "실패: $FAILS건"; exit 1; }
