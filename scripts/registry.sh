#!/usr/bin/env bash
# 로컬 레지스트리 조작. 사용: registry.sh up|down|addr
#  REGISTRY_PROJECT (기본 deploy-registry), REGISTRY_HOST_BIND(기본 127.0.0.1), REGISTRY_HOST_PORT(기본 5000. 시험은 빈 값)
# up은 state/registry.env 에 DEPLOY_REGISTRY=<host:port> 를 쓴다(compose.yaml이 이미지 참조에 쓴다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${REGISTRY_PROJECT:-deploy-registry}
mkdir -p "$DEPLOY_ROOT/state"
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"
run() { "$DOCKER" compose -p "$P" -f "$DEPLOY_ROOT/compose.registry.yaml" --env-file "$LOCK" "$@"; }
case "${1:-}" in
  up)
    # REGISTRY_HOST_PORT 가 빈 값이면 빈 포트를 골라 쓴다(고정 포트 충돌 방지). 충돌하면 다시 고른다.
    port=${REGISTRY_HOST_PORT-5000}
    for try in 1 2 3 4 5; do
      [ -n "${REGISTRY_HOST_PORT+x}" ] && [ -z "${REGISTRY_HOST_PORT}" ] && port=$(free_port)
      # 기동 출력은 버리지 않는다: 실패하면 마지막 줄을 보인다(포트 충돌인지 이미지 문제인지가 이 출력에만 있다)
      if upout=$(REGISTRY_HOST_PORT=$port run up -d 2>&1); then break; fi
      echo "레지스트리 기동 실패(시도 $try/5, 포트 $port): $(printf '%s' "$upout" | tail -3 | tr '\n' ' ')" >&2
      run down >/dev/null 2>&1 || true
      [ "$try" = 5 ] && die "레지스트리를 띄우지 못했다"
    done
    [ -n "$port" ] || die "레지스트리 포트를 읽지 못했다"
    # 준비 확인은 /v2/ 응답이다(컨테이너가 떠도 레지스트리가 응답하기 전에 push 하면 연결 거부로 실패한다). 상한 30초: 측정하지 않았다(D125의 측정 최악 값 없음).
    # 판단 근거: registry:2 는 단일 Go 프로세스라 초 단위로 뜬다고 보고 기존 값 30초를 유지했다. 넘으면 아래 wait_ready 가 마지막 curl 출력을 남기고 실패한다. REGISTRY_READY_TIMEOUT 로 바꾼다.
    wait_ready "레지스트리 /v2/ 응답 (127.0.0.1:$port, 프로젝트 $P)" "${REGISTRY_READY_TIMEOUT:-30}" curl -fsS --connect-timeout 2 --max-time 3 "http://127.0.0.1:$port/v2/" || die "레지스트리가 준비되지 않았다 (registry.env 를 쓰지 않는다)"
    echo "DEPLOY_REGISTRY=127.0.0.1:$port" > "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"
    echo "레지스트리: 127.0.0.1:$port (프로젝트 $P)" ;;
  down) run down "${@:2}" ;;
  addr) cat "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}" ;;
  *) die "사용: registry.sh up|down|addr" ;;
esac
