#!/usr/bin/env bash
# secrets/ 폴더 백업(DB 백업과 별도 스냅샷). 사용: backup-secrets.sh      환경: SECRETS_DIR(기본 secrets/), BACKUP_CONFIG
# 왜 따로인가: DB 백업만 있고 secrets/ 가 없으면 서버를 잃었을 때 DB 암호·서비스 토큰·계정 해시·기기 토큰이 없어 서비스가 다시 서지 못하고,
#   비식별 salt(deid-salt)를 잃으면 이후 가명화 값이 이전과 이어지지 않는다(되돌릴 수 없다). 그래서 secrets/ 전체를 같은 restic 저장소(암호화)에 --host secrets 로 둔다.
# 설정(config/backup.env): backup-lib.sh. 옛 키 BACKUP_SECRETS_DIR/BACKUP_SECRETS_KEEP 는 없어졌다(보관은 BACKUP_RETENTION_DAYS 하나, ADR 0038).
# 암호 파일(BACKUP_PASSWORD_FILE)이 secrets/ 안에 있으면 스냅샷에서 뺀다(같은 암호로 암호화된 저장소 안에 암호를 두는 순환을 만들지 않는다).
# **저장소 암호를 잃으면 이 백업을 포함한 모든 백업을 영영 못 푼다.** 암호는 서버 밖 2곳 이상에 보관한다. 복구: docs/runbook.md 4-6절, scripts/restore-secrets.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
SD=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
[ -d "$SD/tokens" ] || { echo "건너뜀: 비밀 폴더가 없다($SD): 이 서버에는 백업할 비밀이 없다"; exit 0; }
SD=$(readlink -f "$SD"); PW=$(readlink -f "$BACKUP_PASSWORD_FILE")
ex=(); case "$PW" in "$SD"/*) ex=(--exclude "/secrets/${PW#$SD/}");; esac
TS=$(date -u +%Y%m%dT%H%M%SZ)
exec 9>"$BACKUP_LOCK_FILE"; flock -n 9 || { echo "CRIT: 다른 백업이 같은 저장소로 진행 중이다($BACKUP_LOCK_FILE): 겹쳐 돌리지 않는다" >&2; exit 4; }
backup_ensure_repo
# 호스트 사용자로 읽는다(secrets/ 는 호스트 사용자 소유, 폴더 700). root 가 필요 없다
out=$(backup_restic -v "$SD:/secrets:ro" -- backup /secrets --host secrets --tag "set-$TS" "${ex[@]+"${ex[@]}"}" --json) || die "restic backup 실패: secrets"
sid=$(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' <<<"$out" | tail -1); [ -n "$sid" ] || die "스냅샷 ID 를 읽지 못했다: secrets"
echo "비밀 백업: restic 스냅샷 $sid (secrets, 암호화, 값은 출력하지 않는다). 저장소 암호는 서버 밖에 있어야 한다"
backup_forget
