#!/usr/bin/env bash
# 저장소의 논리 지문(SQLite 덤프 해시 + 파일 해시). 서비스가 멈춘 상태에서 복구 시험이 쓴다. 사용: fingerprint.sh <저장소>
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${DEPLOY_PROJECT:-deploy}; LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
"$DOCKER" run --rm -v "${P}_${1}:/src" -v "$DEPLOY_ROOT/scripts:/tool:ro" "$UTIL" python /tool/backup_tool.py finger /src --store "$1" | tr -d '\r'
