#!/usr/bin/env bash
# 외부 이미지(caddy, registry, python 유틸, postgres, 감시 스택 5개)를 받아 digest를 locks/images.lock 의 고정 줄로 기록한다. 이미 있으면 바꾸지 않는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LOCK="$DEPLOY_ROOT/locks/images.lock"; mkdir -p "$DEPLOY_ROOT/locks"; touch "$LOCK"
pin() { # pin <변수> <이름:태그>
  grep -q "^$1=" "$LOCK" && { echo "있음: $1"; return; }
  "$DOCKER" pull -q "$2" >/dev/null
  local d; d=$("$DOCKER" image inspect "$2" --format '{{index .RepoDigests 0}}' | tr -d '\r')
  [ -n "$d" ] || die "$2 digest를 읽지 못했다"
  case "$d" in quay.io/*) echo "$1=$d" >> "$LOCK";; */*@*) echo "$1=docker.io/$d" >> "$LOCK";; *) echo "$1=docker.io/library/$d" >> "$LOCK";; esac; echo "고정: $1=$d"
}
pin GATEWAY_IMAGE caddy:2-alpine
pin REGISTRY_IMAGE registry:2
pin UTIL_IMAGE python:3.12-slim
pin POSTGRES_IMAGE postgres:16   # 공식 이미지. 서비스마다 DB·계정을 나눈 하나의 서버(compose.yaml postgres)
# 감시 스택(compose.monitoring.yaml, ADR 0037). 버전은 고른 시점의 최신 안정 릴리스이고 digest 로 고정한다.
pin PROMETHEUS_IMAGE prom/prometheus:v3.5.0
pin ALERTMANAGER_IMAGE prom/alertmanager:v0.28.1
pin BLACKBOX_IMAGE prom/blackbox-exporter:v0.27.0
pin NODE_EXPORTER_IMAGE prom/node-exporter:v1.9.1
pin JSON_EXPORTER_IMAGE quay.io/prometheuscommunity/json-exporter:v0.7.0
