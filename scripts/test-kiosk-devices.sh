#!/usr/bin/env bash
# gen-secrets.sh 의 기기 토큰 생성·추가·폐기 시험. 옛 Caddyfile 시험(test-gateway-auth.sh)에서 이 부분만 남겼다.
# 왜: 기기 토큰은 deploy 가 만드는 비밀이라 게이트웨이 구현과 무관하게 deploy 가 시험해야 한다.
# 형식은 계약 3.4.10 PublicIngressEnv.INGRESS_DEVICE_TOKENS_DIR 을 따른다.
set -u
DEPLOY_ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); export SECRETS_DIR=$T; trap 'rm -rf "$T"' EXIT
FAILS=0; ok() { local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
K="$DEPLOY_ROOT/scripts/kiosk-add-device.sh"
OUT=$(bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$T" 2>&1)
ok "gen-secrets.sh 성공: 기기마다 파일 하나(devices/<id>, 내용 = 토큰 한 줄)" bash -c '[ "$(ls $1/devices | wc -l)" = 4 ] && [ "$(wc -l < $1/devices/e2e)" = 1 ]' _ "$T"
ok "목록 파일(gateway-devices.caddy)은 더 만들지 않는다" test ! -e "$T/gateway-devices.caddy"
ok "출력에 비밀 값이 없다" bash -c '! grep -qE "[0-9a-f]{40}" <<<"$1"' _ "$OUT"
bash "$K" add lobby-2 >/dev/null 2>&1
ok "기기 5대(기본 4 + 1): list 5줄, 파일 5개, survey 표 5줄" bash -c '[ "$(bash $2 list | wc -l)" = 5 ] && [ "$(ls $1/devices | wc -l)" = 5 ] && [ "$(grep -c "^[a-z0-9-]*=[0-9a-f]\{16,\}$" $1/tokens/survey-kiosk-device-tokens)" = 5 ]' _ "$T" "$K"
ok "기기 파일을 지우고 sync 하면 폐기된다(4대)" bash -c 'rm $1/devices/lobby-2; bash $2 sync; [ "$(ls $1/devices | wc -l)" = 4 ] && [ "$(wc -l < $1/tokens/survey-kiosk-device-tokens)" = 4 ]' _ "$T" "$K"
ok "잘못된 기기 ID 는 거부" bash -c '! bash $1 add "Bad ID"' _ "$K"
ok "기기 0대여도 유효(폴더는 비고 survey 표도 빈다)" bash -c 'rm $1/devices/*; bash $2 sync; [ "$(ls $1/devices | wc -l)" = 0 ] && [ ! -s $1/tokens/survey-kiosk-device-tokens ]' _ "$T" "$K"
[ "$FAILS" = 0 ] && echo "OK" || { echo "FAIL $FAILS"; exit 1; }
