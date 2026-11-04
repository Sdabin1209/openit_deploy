#!/usr/bin/env bash
# D7b: `docker compose up --wait` 가 정상 종료(0)한 일회성 서비스(ops-feedback-migrate 와 같은 모양: restart "no" + 의존 서비스는 service_completed_successfully)를 실패로 보지 않는지,
# 일회성 서비스가 실패(1)하면 up 이 실패하는지 작은 compose 로 확인한다. 제품 이미지는 쓰지 않는다(UTIL_IMAGE 하나). 사용: bash scripts/test-compose-oneshot-wait.sh   (Docker 필요)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
T=$(mktemp -d); P=deploy-oneshot-$$; trap 'docker compose -f "$T/c.yaml" -p $P down -v >/dev/null 2>&1; rm -rf "$T"' EXIT
U=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
mk() { cat > "$T/c.yaml" <<Y
services:
  mig:
    image: $U
    restart: "no"
    command: ["python","-c","import sys;sys.exit($1)"]
  app:
    image: $U
    command: ["python","-c","import time;time.sleep(300)"]
    depends_on:
      mig: {condition: service_completed_successfully}
    healthcheck: {test: ["CMD","python","-c","print(1)"], interval: 2s, retries: 5}
Y
}
F=0; ok() { if "${@:2}" >"$T/out" 2>&1; then echo "  PASS $1"; else echo "  FAIL $1"; tail -3 "$T/out"; F=$((F+1)); fi; }
no() { if "${@:2}" >"$T/out" 2>&1; then echo "  FAIL $1 (성공했다)"; F=$((F+1)); else echo "  PASS $1"; fi; }
# --wait-timeout 60: 측정하지 않았다. 일회성 서비스 하나의 기동·종료 대기라 수 초로 판단한 상한이고, 대기가 실제로 끝나는지를 이 시험이 본다(D125)
up() { docker compose -f "$T/c.yaml" -p $P up -d --wait --wait-timeout 60; }
mk 0
ok "일회성 서비스가 0 으로 끝나면 up --wait 가 성공한다" up
ok "이미 끝난 일회성 서비스가 있는 상태에서 다시 up --wait 해도 성공한다(재기동·갱신 경로)" up
ok "일회성 서비스는 종료 코드 0 으로 남고 의존 서비스는 떠 있다" bash -c "docker compose -f '$T/c.yaml' -p $P ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | tr '\n' ' ' | grep -q 'app running 0' && docker compose -f '$T/c.yaml' -p $P ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | grep -q 'mig exited 0'"
docker compose -f "$T/c.yaml" -p $P down -v >/dev/null 2>&1
mk 1
no "일회성 서비스가 실패(1)하면 up --wait 가 실패한다(의존 서비스가 뜨지 않는다)" up
echo; [ $F = 0 ] && echo "통과: 일회성 서비스 up --wait 시험 (docker compose $(docker compose version --short))" || { echo "실패: $F건"; exit 1; }
