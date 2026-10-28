#!/usr/bin/env bash
# 저장소(볼륨) 복구. 사용: restore.sh <저장소> <latest|스냅샷 ID> --yes     환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG, REGISTRY_PROJECT
# 그 저장소를 쓰는 서비스가 멈춰 있어야 한다(떠 있으면 거부). 볼륨을 비운 뒤 restic 이 내용 해시를 검증하며(--verify) 복원한다. 소유자·모드는 백업 때 값 그대로 돌아온다(root 로 복원).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
S=${1:?저장소}; SNAP=$(backup_snapshot_arg "${2:?스냅샷(latest 또는 ID)}"); [ "${3:-}" = "--yes" ] || die "--yes 가 필요하다(볼륨을 비운다)"
[[ "$S" =~ ^[a-z][a-z0-9-]*$ ]] || die "저장소 이름 형식 오류: $S"
BACKUP_CHECK_ONLY=1 backup_load_config
P=${DEPLOY_PROJECT:-deploy}
case "$S" in registry-data) V="${REGISTRY_PROJECT:-deploy-registry}_registry-data";; *) V="${P}_$S";; esac
using=$("$DOCKER" ps -q --filter "volume=$V" | tr -d '\r')
[ -z "$using" ] || die "$V 를 쓰는 컨테이너가 떠 있다. 서비스를 먼저 멈춘다(compose stop)"
"$DOCKER" volume inspect "$V" >/dev/null 2>&1 || "$DOCKER" volume create "$V" >/dev/null
# 비우고 복원은 한 컨테이너에서 한다(비운 뒤 복원이 실패하면 비어 있는 채로 끝나므로 종료 코드로 드러낸다)
backup_restic "${BACKUP_ROOT_ARGS[@]}" -v "$V:/dst" --entrypoint sh -- -c 'find /dst -mindepth 1 -delete && restic restore "$0:/data" --host "$1" --target /dst --verify' "$SNAP" "$S" >/dev/null || die "복원 실패: $S (스냅샷 $SNAP). 볼륨이 비어 있을 수 있다"
echo "복구: $S <- restic 스냅샷 $SNAP"
