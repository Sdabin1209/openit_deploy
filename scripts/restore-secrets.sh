#!/usr/bin/env bash
# secrets/ 복구. 사용: restore-secrets.sh <latest|스냅샷 ID> <대상 폴더> --yes     환경: BACKUP_CONFIG(저장소 위치·암호 파일). 암호는 사람이 서버 밖 보관본에서 가져와 BACKUP_PASSWORD_FILE 에 둔다(runbook 4-6절)
# 대상 폴더는 없거나 비어 있어야 한다(기존 비밀을 덮어쓰지 않는다). restic 이 내용 해시를 검증하며 복원한다. 복원 뒤 lib.sh secret_mode 대로 모드를 바로잡는다(값은 건드리지 않는다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
SNAP=$(backup_snapshot_arg "${1:?스냅샷(latest 또는 ID)}"); DST=${2:?대상 폴더}; [ "${3:-}" = --yes ] || die "--yes 가 필요하다"
BACKUP_CHECK_ONLY=1 backup_load_config
if [ -d "$DST" ] && [ -n "$(ls -A "$DST" 2>/dev/null)" ]; then die "대상 폴더가 비어 있지 않다: $DST (기존 비밀을 덮어쓰지 않는다)"; fi
( umask 077; mkdir -p "$DST" ); DST=$(readlink -f "$DST"); chmod 700 "$DST"
backup_restic -v "$DST:/target" -- restore "$SNAP:/secrets" --host secrets --target /target --verify >/dev/null || die "restic restore 실패 (스냅샷 $SNAP)"
chmod 700 "$DST" "$DST/tokens" 2>/dev/null || true
for f in "$DST"/tokens/*; do [ -f "$f" ] && chmod "$(secret_mode "$(basename "$f")")" "$f"; done   # 모드 바로잡기(값은 건드리지 않는다)
for f in "$DST"/gateway-*.caddy; do [ -f "$f" ] && chmod 644 "$f"; done; [ ! -d "$DST/kiosk-config" ] || chmod -R u=rwX,go= "$DST/kiosk-config"
echo "복구: $DST ($(find "$DST" -type f | wc -l)개 파일). 이어서: bash scripts/check-secret-perms.sh $DST"
