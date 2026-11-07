#!/usr/bin/env bash
# kiosk-add-device.sh 가 쓰는 기기 설정(secrets/kiosk-config/<ID>.json)이 계약 DeviceConfig 를 통과하는지 본다(R7: 만드는 쪽이 쓰기 전에 검증). 정상이면 파일이 계약을 통과하고 모드 600, 계약을 어기는 문진표 ID(공백 포함)면 파일을 바꾸지 않고 실패한다. 4.0.0(D136): 기기 설정에 기기 토큰 칸은 없다.
# 임시 SECRETS_DIR 만 쓴다(Docker 불필요). 사용: bash scripts/test-kiosk-device-config.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
ok() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; tail -3 "$T/out" | sed 's/^/     /'; F=$((F+1)); fi; }
no() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  FAIL $n (성공했다)"; F=$((F+1)); else echo "  PASS $n"; fi; }
export DEVICE_ALLOWLIST_DIR="$T/allow"; mkdir -p "$T/s"; chmod 700 "$T/s"; S=$T/s   # 시험용 비밀 폴더와 허용 목록(개발용 기기 CA 를 먼저 만든다)
source "$HERE/gateway-lib.sh"; gw_device_ca_init "$S" || { echo "개발용 CA 실패"; exit 1; }
add() { SECRETS_DIR="$S" bash "$HERE/kiosk-add-device.sh" add "$1"; }

ok "정상: 기기 추가" add dev-a
ok "정상: 산출물이 계약 DeviceConfig 를 통과한다" "$DEPLOY_PY" -W ignore -c "import json,sys;from boundary_contracts import validator;d=json.load(open('$S/kiosk-config/dev-a.json'));e=list(validator('DeviceConfig').iter_errors(d));sys.exit(1 if e or 'device_token' in d else 0)"
ok "정상: 산출물 모드가 600" bash -c "[ \"\$(stat -c %a '$S/kiosk-config/dev-a.json')\" = 600 ]"
ok "산출물에 기기 토큰 칸이 없다(D136)" bash -c "! grep -q device_token '$S/kiosk-config/dev-a.json'"
# 문진표 배치(계약 3.3.0 DeviceConfig.question_set_id, ADR 0052)
qsof() { "$DEPLOY_PY" -W ignore -c "import json;print(json.load(open('$S/kiosk-config/$1.json')).get('question_set_id','-'))"; }
cat > "$T/chk.py" <<'PY'
import json, sys
from boundary_contracts import validator
d = json.load(open(sys.argv[1]))
sys.exit(1 if list(validator("DeviceConfig").iter_errors(d)) or d.get("question_set_id") != sys.argv[2] else 0)
PY
ok "배치: add --question-set 이 기기 설정에 문진표 ID 를 쓴다" env SECRETS_DIR="$S" bash "$HERE/kiosk-add-device.sh" add dev-p --question-set health-screening
ok "배치: 그 기기 설정이 계약 DeviceConfig 를 통과하고 문진표 ID 가 맞다" "$DEPLOY_PY" -W ignore "$T/chk.py" "$S/kiosk-config/dev-p.json" health-screening
ok "배치 없는 기기에는 question_set_id 칸이 없다" bash -c "[ \"\$(cd '$S' && '$DEPLOY_PY' -W ignore -c \"import json;print('question_set_id' in json.load(open('kiosk-config/dev-a.json')))\")\" = False ]"
ok "rotate 는 배치를 그대로 둔다" bash -c "SECRETS_DIR='$S' bash '$HERE/kiosk-add-device.sh' rotate dev-p && grep -q '\"question_set_id\": \"health-screening\"' '$S/kiosk-config/dev-p.json'"
ok "place 로 배치를 바꾼다" bash -c "SECRETS_DIR='$S' bash '$HERE/kiosk-add-device.sh' place dev-p health-screening-b && grep -q 'health-screening-b' '$S/kiosk-config/dev-p.json'"
ok "place - 로 배치를 해제한다" bash -c "SECRETS_DIR='$S' bash '$HERE/kiosk-add-device.sh' place dev-p - && ! grep -q question_set_id '$S/kiosk-config/dev-p.json'"
no "계약을 어기는 문진표 ID(공백)는 거부하고 기존 산출물을 그대로 둔다" bash -c "SECRETS_DIR='$S' bash '$HERE/kiosk-add-device.sh' place dev-a 'bad id'"
no "거부된 뒤에도 dev-a 에는 배치가 없다" grep -q question_set_id "$S/kiosk-config/dev-a.json"
printf 'dev-l1 health-screening\ndev-l2\n' > "$T/list.conf"
ok "목록 파일의 둘째 칸이 배치가 된다" bash -c "SECRETS_DIR='$S' bash '$HERE/kiosk-add-device.sh' from-list '$T/list.conf' && grep -q health-screening '$S/kiosk-config/dev-l1.json' && ! grep -q question_set_id '$S/kiosk-config/dev-l2.json'"
echo; [ $F = 0 ] && echo "통과: 기기 설정 계약 검증 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
