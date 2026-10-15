#!/usr/bin/env bash
# 로컬 레지스트리 조작. 사용: registry.sh up|down|addr
#  REGISTRY_PROJECT (기본 deploy-registry), REGISTRY_HOST_BIND(기본 127.0.0.1), REGISTRY_HOST_PORT(기본 5000. 시험은 빈 값)
# up은 state/registry.env 에 DEPLOY_REGISTRY=<host:port> 를 쓴다(compose.yaml이 이미지 참조에 쓴다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${REGISTRY_PROJECT:-deploy-registry}
mkdir -p "$DEPLOY_ROOT/state"
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"
run() {
  local ef; ef=$(mktemp); envfile "$ef"; trap 'rm -f "$ef"' RETURN
  "$DOCKER" compose -p "$P" -f "$(hostpath "$DEPLOY_ROOT/compose.registry.yaml")" --env-file "$(hostpath "$LOCK")" --env-file "$(hostpath "$ef")" "$@"
}
case "${1:-}" in
  up)
    # REGISTRY_HOST_PORT 가 빈 값이면 빈 포트를 골라 쓴다(고정 포트 충돌 방지). 충돌하면 다시 고른다.
    port=${REGISTRY_HOST_PORT-5000}
    for try in 1 2 3 4 5; do
      [ -n "${REGISTRY_HOST_PORT+x}" ] && [ -z "${REGISTRY_HOST_PORT}" ] && port=$(free_port)
      if REGISTRY_HOST_PORT=$port run up -d >/dev/null 2>&1; then break; fi   # 함수 호출에 붙인 변수는 envfile이 읽는다
      run down >/dev/null 2>&1 || true
      [ "$try" = 5 ] && die "레지스트리를 띄우지 못했다"
    done
    [ -n "$port" ] || die "레지스트리 포트를 읽지 못했다"
    for _ in $(seq 1 30); do curl -fsS "http://127.0.0.1:$port/v2/" >/dev/null 2>&1 && break; sleep 1; done
    echo "DEPLOY_REGISTRY=127.0.0.1:$port" > "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"
    echo "레지스트리: 127.0.0.1:$port (프로젝트 $P)" ;;
  down) run down "${@:2}" ;;
  addr) cat "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}" ;;
  *) die "사용: registry.sh up|down|addr" ;;
esac
