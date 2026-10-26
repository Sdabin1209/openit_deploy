#!/usr/bin/env bash
# 사용: up.sh <프로젝트> [compose up 인자...]   기본 프로젝트는 deploy. 시험은 COMPOSE_EXTRA=compose.test.yaml 로 덮어쓴다.
set -euo pipefail
# 서버 기동용 사전 점검(docker·compose·데몬·자격증명). 건너뛰기: DEPLOY_SKIP_DOCTOR=1
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" --up || exit 1
source "$(dirname "$0")/lib.sh"
P=${1:-deploy}; shift || true
bash "$DEPLOY_ROOT/scripts/check-compose.sh" >/dev/null
dc "$P" up -d --wait "$@"
