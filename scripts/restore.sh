#!/usr/bin/env bash
# 저장소 복구. 사용: restore.sh <저장소> <스냅샷 디렉터리> --yes
# 그 저장소를 쓰는 서비스가 멈춰 있어야 한다(떠 있으면 거부). 해시를 검증한 뒤 볼륨을 비우고 복원한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
S=${1:?저장소}; SNAP=${2:?스냅샷}; [ "${3:-}" = "--yes" ] || die "--yes 가 필요하다(볼륨을 비운다)"
P=${DEPLOY_PROJECT:-deploy}
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
using=$("$DOCKER" ps -q --filter "volume=${P}_${S}" | tr -d '\r')
[ -z "$using" ] || die "${P}_${S} 를 쓰는 컨테이너가 떠 있다. 서비스를 먼저 멈춘다(compose stop)"
"$DOCKER" run --rm -v "${P}_${S}:/dst" -v "$(hostpath "$SNAP"):/snap:ro" -v "$(hostpath "$DEPLOY_ROOT/scripts"):/tool:ro" \
  "$UTIL" python /tool/backup_tool.py restore /snap /dst --uid 10001 --gid 10001
echo "복구: $S <- $SNAP"
