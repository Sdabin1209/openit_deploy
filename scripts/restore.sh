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
# 왜 볼륨 루트의 소유자·모드를 따로 되돌리나: `restic restore <스냅샷>:/data` 는 /data 아래 항목의 소유자·모드는 되살리지만 대상 폴더(/dst, 볼륨 루트) 자체의 속성은 건드리지 않는다.
# 새로 만든 볼륨의 루트는 root:root 755 라 비root 서비스(model-registry, dataset-store 등)가 쓰지 못해 unhealthy 가 된다(E2E 로 확인). 그래서 스냅샷에 기록된 /data 노드의 uid·gid·모드를 읽어 볼륨 루트에 적용한다.
backup_restic "${BACKUP_ROOT_ARGS[@]}" -v "$V:/dst" --entrypoint sh -- -c '
set -e
find /dst -mindepth 1 -delete
restic restore "$0:/data" --host "$1" --target /dst --verify
meta=$(restic ls --json "$0" --host "$1" /data | grep -m1 "\"path\":\"/data\"" || true)
[ -n "$meta" ] || { echo "스냅샷에 /data 노드 정보가 없다: 볼륨 루트 속성을 되돌리지 못했다" >&2; exit 3; }
uid=$(echo "$meta" | sed -n "s/.*\"uid\":\([0-9]*\).*/\1/p"); gid=$(echo "$meta" | sed -n "s/.*\"gid\":\([0-9]*\).*/\1/p"); mode=$(echo "$meta" | sed -n "s/.*\"mode\":\([0-9]*\).*/\1/p")
[ -n "$uid" ] && [ -n "$gid" ] && [ -n "$mode" ] || { echo "/data 노드의 uid·gid·mode 를 읽지 못했다" >&2; exit 3; }
chown "$uid:$gid" /dst
chmod "$(printf "%o" $((mode & 511)))" /dst
' "$SNAP" "$S" >/dev/null || die "복원 실패: $S (스냅샷 $SNAP). 볼륨이 비어 있을 수 있다"
echo "복구: $S <- restic 스냅샷 $SNAP"
