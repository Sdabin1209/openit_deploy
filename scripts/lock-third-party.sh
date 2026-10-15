#!/usr/bin/env bash
# 외부 이미지(caddy, registry, python 유틸)를 받아 digest를 locks/images.lock 의 고정 줄로 기록한다. 이미 있으면 바꾸지 않는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LOCK="$DEPLOY_ROOT/locks/images.lock"; mkdir -p "$DEPLOY_ROOT/locks"; touch "$LOCK"
pin() { # pin <변수> <이름:태그>
  grep -q "^$1=" "$LOCK" && { echo "있음: $1"; return; }
  "$DOCKER" pull -q "$2" >/dev/null
  local d; d=$("$DOCKER" image inspect "$2" --format '{{index .RepoDigests 0}}' | tr -d '\r')
  [ -n "$d" ] || die "$2 digest를 읽지 못했다"
  echo "$1=docker.io/library/$d" >> "$LOCK"; echo "고정: $1=$d"
}
pin GATEWAY_IMAGE caddy:2-alpine
pin REGISTRY_IMAGE registry:2
pin UTIL_IMAGE python:3.12-slim
