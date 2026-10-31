#!/usr/bin/env bash
# kiosk-add-device.sh 가 쓰는 기기 설정(secrets/kiosk-config/<ID>.json)이 계약 DeviceConfig 를 통과하는지 본다(R7: 만드는 쪽이 쓰기 전에 검증). 정상 토큰이면 파일이 계약을 통과하고 모드 600, 계약을 어기는 토큰(공백 포함)이면 파일을 만들지 않고 실패하며 출력에 토큰 값이 없다.
# 임시 SECRETS_DIR 만 쓴다(Docker 불필요). 사용: bash scripts/test-kiosk-device-config.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
ok() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; tail -3 "$T/out" | sed 's/^/     /'; F=$((F+1)); fi; }
no() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  FAIL $n (성공했다)"; F=$((F+1)); else echo "  PASS $n"; fi; }
mkdir -p "$T/tokens"; chmod 700 "$T/tokens"
add() { SECRETS_DIR="$T" bash "$HERE/kiosk-add-device.sh" add "$1"; }
ok "정상: 기기 추가" add dev-a
ok "정상: 산출물이 계약 DeviceConfig 를 통과한다" "$DEPLOY_PY" -W ignore -c "import json,sys;from boundary_contracts import validator;d=json.load(open('$T/kiosk-config/dev-a.json'));e=list(validator('DeviceConfig').iter_errors(d));sys.exit(1 if e or not d.get('device_token') else 0)"
ok "정상: 산출물 모드가 600" bash -c "[ \"\$(stat -c %a '$T/kiosk-config/dev-a.json')\" = 600 ]"
printf 'has space token' > "$T/tokens/kiosk-device-dev-b"; chmod 600 "$T/tokens/kiosk-device-dev-b"
no "계약을 어기는 토큰(공백)이면 add 가 실패한다" add dev-b
no "실패하면 산출물을 만들지 않는다" test -e "$T/kiosk-config/dev-b.json"
no "실패 출력에 토큰 값이 없다" bash -c "SECRETS_DIR='$T' bash '$HERE/kiosk-add-device.sh' add dev-b 2>&1 | grep -q 'has space'"
ok "다른 기기의 산출물은 그대로다" test -s "$T/kiosk-config/dev-a.json"
echo; [ $F = 0 ] && echo "통과: 기기 설정 계약 검증 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
