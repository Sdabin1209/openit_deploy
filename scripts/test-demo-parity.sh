#!/usr/bin/env bash
# 데모=제품 정적 점검(U75): 데모 덮어쓰기(demo/*.yaml, test/compose.sandbox.yaml)는 제품 compose 의 서비스 설정·경로를 바꾸지 못한다.
# 허용되는 차이는 세 가지뿐이다: (1) model-serving 의 모델 대역(mimic/vllm 과 그 입력 파일), (2) 호스트 포트 배정, (3) 시험 계정·기기(gen-secrets --test-fixtures, kiosk-add-device).
# 사용: bash scripts/test-demo-parity.sh   (컨테이너를 띄우지 않는다. 값은 출력하지 않는다)
set -uo pipefail
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/testlib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
FAILS=0; ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; printf '%s\n' "$out" | tail -3 | cut -c1-200; FAILS=$((FAILS+1)); fi; }
export DEPLOY_LOCK=$T/images.lock DEPLOY_REGISTRY_ENV=$T/registry.env SECRETS_DIR=$T/secrets
test_lock_copy "$DEPLOY_LOCK"; echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$DEPLOY_REGISTRY_ENV"
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null 2>&1
export DEMO_MIMIC_FLOW_FILE=$DEPLOY_ROOT/test/fake-model/question_flow.json
dc_cfg() { COMPOSE_EXTRA="$1" dc demo-parity config 2>/dev/null; }
dc_cfg "" > "$T/prod.yaml"; dc_cfg "$DEPLOY_ROOT/test/compose.sandbox.yaml $DEPLOY_ROOT/demo/compose.demo-mimic.yaml" > "$T/demo.yaml"
ok "제품·데모 병합 설정 생성" test -s "$T/prod.yaml" -a -s "$T/demo.yaml"
# 데모 덮어쓰기 파일 목록은 고정이다. 새 파일이 생기면 이 점검을 고쳐야 한다(허용 차이 재검토)
ok "데모 덮어쓰기 파일은 compose.demo-mimic.yaml 하나" test "$(ls "$DEPLOY_ROOT"/demo/*.yaml | wc -l)" = 1
ok "데모는 게이트웨이 설정(configs)·Caddyfile 을 바꾸지 않는다" bash -c '! grep -nE "configs:|Caddyfile" "$0"/demo/*.yaml "$0"/scripts/demo.sh | grep -v "^.*#" | grep -qE "configs:|Caddyfile\.demo|demo_caddyfile"' "$DEPLOY_ROOT"
ok "데모는 kiosk-frontend·gateway 에 아무것도 마운트하지 않는다" "$DEPLOY_PY" -I - "$T/prod.yaml" "$T/demo.yaml" <<'PY'
import sys, yaml
prod, demo = (yaml.safe_load(open(p)) for p in sys.argv[1:3])
for svc in ("kiosk-frontend", "gateway", "survey-service", "release-gate", "question-authoring", "ops-feedback", "model-registry", "dataset-store", "admin-console"):
    a, b = prod["services"].get(svc, {}), demo["services"].get(svc, {})
    for k in ("volumes", "configs", "image", "command", "entrypoint", "env_file"):
        assert a.get(k) == b.get(k), (svc, k)
    ea, eb = a.get("environment", {}) or {}, b.get("environment", {}) or {}
    allowed = {"release-gate": {"GATE_POLL_SECONDS"}}.get(svc, set())   # 데모가 승인 판정을 빨리 돌리기 위한 값 하나(제품 60초 -> 데모 2초). 로직이 아니라 주기
    diff = {k for k in set(ea) | set(eb) if ea.get(k) != eb.get(k)}
    assert diff <= allowed, (svc, sorted(diff))
ms_a, ms_b = prod["services"]["model-serving"], demo["services"]["model-serving"]
assert ms_a["image"] == ms_b["image"]   # 같은 model-runtime 이미지. 백엔드만 mimic (모델 대역, 허용 차이 1)
PY
ok "demo.sh 는 기기 토큰 값을 출력하지 않는다(안내문은 파일 경로만)" bash -c '! grep -nE "cat .*kiosk-device-|echo .*kiosk-device-" "$0"' "$DEPLOY_ROOT/scripts/demo.sh"
echo; [ "$FAILS" = 0 ] && echo "test-demo-parity: 전부 통과" || echo "test-demo-parity: 실패 $FAILS건"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
