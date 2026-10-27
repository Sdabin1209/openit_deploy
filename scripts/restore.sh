#!/usr/bin/env bash
# 저장소 복구. 사용: restore.sh <저장소> <스냅샷 디렉터리> --yes
# 그 저장소를 쓰는 서비스가 멈춰 있어야 한다(떠 있으면 거부). 해시를 검증한 뒤 볼륨을 비우고 복원한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
S=${1:?저장소}; SNAP=${2:?스냅샷}; [ "${3:-}" = "--yes" ] || die "--yes 가 필요하다(볼륨을 비운다)"
P=${DEPLOY_PROJECT:-deploy}
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
if [ ! -f "$SNAP/MANIFEST.json" ] || ! grep -q '"format": "tar"' "$SNAP/MANIFEST.json"; then :; else   # tar 로 묶인(암호화 백업) 스냅샷: 풀어서 쓴다
  if [ ! -f "$SNAP/$S.tar" ]; then for e in age gpg; do [ -f "$SNAP/$S.tar.$e" ] && die "스냅샷이 암호화되어 있다: $SNAP/$S.tar.$e 를 개인키로 복호해 $SNAP/$S.tar 로 둔다 (age -d -i <키> -o ... / gpg -d -o ...). docs/runbook.md 4절"; done; fi
  [ -f "$SNAP/$S.tar" ] || die "스냅샷에 $S.tar 가 없다: $SNAP"
  UNTAR=$(mktemp -d); chmod 700 "$UNTAR"; trap 'rm -rf "$UNTAR"' EXIT
  tar -C "$UNTAR" -xf "$SNAP/$S.tar"; SNAP=$UNTAR
fi
using=$("$DOCKER" ps -q --filter "volume=${P}_${S}" | tr -d '\r')
[ -z "$using" ] || die "${P}_${S} 를 쓰는 컨테이너가 떠 있다. 서비스를 먼저 멈춘다(compose stop)"
"$DOCKER" run --rm -v "${P}_${S}:/dst" -v "$SNAP:/snap:ro" -v "$DEPLOY_ROOT/scripts:/tool:ro" \
  "$UTIL" python /tool/backup_tool.py restore /snap /dst --uid 10001 --gid 10001
echo "복구: $S <- $SNAP"
