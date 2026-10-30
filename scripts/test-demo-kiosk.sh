#!/usr/bin/env bash
# 데모 구성 자체 시험(작업 지시서 2): 모방 백엔드 환경 변수, 키오스크 /config.json 배선, 운영 구성 불변을 병합된 compose 설정과 Caddyfile 사본으로 확인한다.
# 사용: bash scripts/test-demo-kiosk.sh   (컨테이너를 띄우지 않는다. caddy validate 만 일회용 컨테이너로 돈다. 값은 출력하지 않는다)
set -uo pipefail
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/testlib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
FAILS=0; ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; printf '%s\n' "$out" | tail -3 | cut -c1-200; FAILS=$((FAILS+1)); fi; }
export DEPLOY_LOCK=$T/images.lock DEPLOY_REGISTRY_ENV=$T/registry.env SECRETS_DIR=$T/secrets
COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $DEPLOY_ROOT/test/compose.demo-mimic.yaml $DEPLOY_ROOT/test/compose.demo-kiosk.yaml"
test_lock_copy "$DEPLOY_LOCK"; echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$DEPLOY_REGISTRY_ENV"
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null 2>&1
bash "$DEPLOY_ROOT/scripts/kiosk-add-device.sh" add e2e >/dev/null 2>&1
export DEMO_MIMIC_FLOW_FILE=$DEPLOY_ROOT/test/fake-model/question_flow.json DEMO_CADDYFILE=$T/Caddyfile.demo DEMO_KIOSK_CONFIG=$SECRETS_DIR/kiosk-config/e2e.json

ok "기기 산출물(kiosk-add-device.sh add e2e)이 만들어졌다" test -s "$DEMO_KIOSK_CONFIG"
ok "Caddyfile 사본 생성" "$DEPLOY_PY" -I "$DEPLOY_ROOT/scripts/demo_caddyfile.py" "$DEPLOY_ROOT/config/Caddyfile" "$DEMO_CADDYFILE"
ok "사본과 운영 Caddyfile 의 차이는 /config.json 블록 하나뿐이다(diff 덩어리 1개)" bash -c '[ "$(diff "$1" "$2" | grep -c "^[0-9]")" = 1 ] && diff "$1" "$2" | grep -q "reverse_proxy kiosk-frontend" && ! grep -A1 "handle /config.json" "$2" | grep -q 404' _ "$DEPLOY_ROOT/config/Caddyfile" "$DEMO_CADDYFILE"
ok "운영 Caddyfile 은 여전히 /config.json 을 404 로 막는다" bash -c 'grep -A1 "handle /config.json" "$1" | grep -q "404"' _ "$DEPLOY_ROOT/config/Caddyfile"
ok "블록이 없는 Caddyfile 이면 사본 생성이 실패한다(조용히 틀어지지 않는다)" bash -c 'echo "x" > $1/none; ! "$3" -I $2/scripts/demo_caddyfile.py $1/none $1/out' _ "$T" "$DEPLOY_ROOT" "$DEPLOY_PY"

DEMO=$(dc deploy-demotest --profile jobs config 2>&1); echo "$DEMO" > "$T/demo.yaml"
PROD=$(COMPOSE_EXTRA="" dc deploy-prodtest --profile jobs config 2>&1); echo "$PROD" > "$T/prod.yaml"
ok "데모 구성 병합 성공(docker compose config)" grep -q "^services:" "$T/demo.yaml"
ok "운영 구성 병합 성공" grep -q "^services:" "$T/prod.yaml"
svc() { awk -v s="  $2:" '$0==s{f=1;next} f&&/^  [^ ]/{f=0} f' "$1"; }
ok "model-serving: BACKEND=mimic" bash -c 'svc() { awk -v s="  $2:" '"'"'$0==s{f=1;next} f&&/^  [^ ]/{f=0} f'"'"' "$1"; }; svc "$1" model-serving | grep -q "MODEL_RUNTIME_BACKEND: mimic"' _ "$T/demo.yaml" 
ok "model-serving: ALLOW_FAKE=1 과 흐름 파일 경로" bash -c 'svc() { awk -v s="  $2:" '"'"'$0==s{f=1;next} f&&/^  [^ ]/{f=0} f'"'"' "$1"; }; o=$(svc "$1" model-serving); grep -q "MODEL_RUNTIME_ALLOW_FAKE: \"1\"" <<<"$o" && grep -q "MODEL_RUNTIME_FAKE_FLOW_FILE: /test-mimic/question_flow.json" <<<"$o" && grep -q "source: $2" <<<"$o"' _ "$T/demo.yaml" "$DEMO_MIMIC_FLOW_FILE"
ok "kiosk-frontend(데모): CONFIG_FILE 과 기기 산출물 마운트(읽기 전용)" bash -c 'svc() { awk -v s="  $2:" '"'"'$0==s{f=1;next} f&&/^  [^ ]/{f=0} f'"'"' "$1"; }; o=$(svc "$1" kiosk-frontend); grep -q "CONFIG_FILE: /run/kiosk-device/config.json" <<<"$o" && grep -q "source: $2" <<<"$o" && grep -A3 "source: $2" <<<"$o" | grep -q "read_only: true"' _ "$T/demo.yaml" "$DEMO_KIOSK_CONFIG"
ok "gateway 설정(데모): 사본을 쓴다" grep -q "file: $DEMO_CADDYFILE" "$T/demo.yaml"
ok "운영: kiosk-frontend 에 CONFIG_FILE 도 기기 파일 마운트도 없다" bash -c '! awk '"'"'$0=="  kiosk-frontend:"{f=1;next} f&&/^  [^ ]/{f=0} f'"'"' "$1" | grep -qE "CONFIG_FILE|kiosk-config|volumes:"' _ "$T/prod.yaml"
ok "운영: gateway 는 config/Caddyfile 을 쓴다" grep -q "file: $DEPLOY_ROOT/config/Caddyfile" "$T/prod.yaml"
ok "운영: 모방 백엔드가 없다" bash -c '! grep -q "mimic" "$1"' _ "$T/prod.yaml"
ok "demo.sh --mimic-flow-file 에 값이 없으면 거부" bash -c '! bash $1/scripts/demo.sh up --mimic-flow-file' _ "$DEPLOY_ROOT"
ok "demo.sh 안내 출력에 토큰 값을 쓰지 않는다(토큰 파일 내용이 demo.sh 에 없다)" bash -c '! grep -qF "$(python3 -I -c "import json,sys;print(json.load(open(sys.argv[1]))[\"device_token\"])" "$1")" "$2"' _ "$DEMO_KIOSK_CONFIG" "$DEPLOY_ROOT/scripts/demo.sh"
if command -v docker >/dev/null 2>&1 && GW=$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock") && [ -n "$GW" ] && docker image inspect "$GW" >/dev/null 2>&1; then
  ok "Caddyfile 사본이 caddy validate 통과" docker run --rm -v "$DEMO_CADDYFILE:/etc/caddy/Caddyfile:ro" -v "$DEPLOY_ROOT/config/device-tls.caddy:/etc/caddy/device-tls.caddy:ro" -v "$DEPLOY_ROOT/config/device-ca.pem:/etc/caddy/device-ca.pem:ro" -v "$SECRETS_DIR/gateway-accounts.caddy:/etc/caddy/accounts.caddy:ro" -v "$SECRETS_DIR/gateway-devices.caddy:/etc/caddy/devices.caddy:ro" -v "$SECRETS_DIR/tokens:/run/secrets:ro" "$GW" caddy validate --config /etc/caddy/Caddyfile
else echo "  SKIP caddy validate (gateway 이미지가 로컬에 없다)"; fi
[ $FAILS = 0 ] && echo "OK 데모 구성 자체 시험" || { echo "FAIL ${FAILS}건"; exit 1; }
