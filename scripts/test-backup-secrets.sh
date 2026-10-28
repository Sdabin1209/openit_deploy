#!/usr/bin/env bash
# backup-secrets.sh / restore-secrets.sh 자체 시험(Docker 필요: restic 은 digest 고정 이미지로 돈다, ADR 0038). 사용: bash scripts/test-backup-secrets.sh
# 핵심: secrets/ 를 통째로 잃은 뒤 백업에서 되살리면 deid-salt 가 **같은 값으로** 돌아오는지. 값은 출력하지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); chmod 700 "$T"; trap 'rm -rf "$T"' EXIT
N=0; F=0
t() { local name=$1 want=$2; shift 2; N=$((N+1)); out=$("$@" 2>&1); local rc=$?; if [ $rc = "$want" ]; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want) $(echo "$out" | tail -1 | cut -c1-160)"; F=$((F+1)); fi; }
ck() { N=$((N+1)); local name=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; F=$((F+1)); fi; }
S="$T/secrets"; bash "$HERE/gen-secrets.sh" --db-only "$S" >/dev/null 2>&1
python3 -c 'import secrets;print(secrets.token_hex(24))' > "$S/tokens/deid-salt"; chmod 644 "$S/tokens/deid-salt"
mkdir -p "$S/kiosk-config"; echo '{"device_token":"x"}' > "$S/kiosk-config/e2e.json"
SALT_SHA=$(sha256sum "$S/tokens/deid-salt" | cut -d' ' -f1); PW_SHA=$(sha256sum "$S/tokens/postgres-password" | cut -d' ' -f1)
SALT=$(cat "$S/tokens/deid-salt")
( umask 077; echo "sectest-password-$$-not-a-secret" > "$T/backup.pass" )
printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$T" "$T/backup.pass" > "$T/backup.env"
export BACKUP_CONFIG="$T/backup.env" SECRETS_DIR="$S"
t "백업 성공" 0 bash "$HERE/backup-secrets.sh"
ck "저장소 폴더 700, 저장소 파일에 salt 값이 없다(암호화)" bash -c "[ \"\$(stat -c %a '$T/bk')\" = 700 ] && ! grep -rqaF '$SALT' '$T/bk/restic'"
t "백업 출력에 salt 값이 없다" 1 bash -c "bash '$HERE/backup-secrets.sh' | grep -F '$SALT'"
printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\nBACKUP_SECRETS_KEEP=2\n' "$T" "$T/backup.pass" > "$T/old.env"
t "옛 키(BACKUP_SECRETS_KEEP)가 남아 있으면 거부(2)" 2 env BACKUP_CONFIG="$T/old.env" bash "$HERE/backup-secrets.sh"
t "설정 없으면 CRIT(2)" 2 env BACKUP_CONFIG="$T/none.env" bash "$HERE/backup-secrets.sh"
# 암호 파일이 secrets/ 안에 있으면 스냅샷에서 뺀다(같은 암호로 암호화한 저장소 안에 암호를 두지 않는다)
mkdir -p "$S/backup"; ( umask 077; cp "$T/backup.pass" "$S/backup/restic.pass" ); printf 'BACKUP_DIR=%s/bk2\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$T" "$S/backup/restic.pass" > "$T/in.env"
t "암호 파일이 secrets/ 안에 있어도 백업된다" 0 env BACKUP_CONFIG="$T/in.env" bash "$HERE/backup-secrets.sh"
echo "== 분실 시나리오: secrets/ 를 통째로 지운다 -> 저장소 암호로 복구"
rm -rf "$S"
ck "salt 가 없어졌다" test ! -e "$S/tokens/deid-salt"
( umask 077; echo wrong > "$T/wrong.pass" ); printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$T" "$T/wrong.pass" > "$T/bw.env"
t "틀린 암호로는 복구할 수 없다" 1 env BACKUP_CONFIG="$T/bw.env" bash "$HERE/restore-secrets.sh" latest "$T/dst-wrong" --yes
t "restore-secrets.sh" 0 bash "$HERE/restore-secrets.sh" latest "$S" --yes
ck "deid-salt 가 같은 값으로 돌아왔다" bash -c "[ \"\$(sha256sum '$S/tokens/deid-salt' | cut -d' ' -f1)\" = '$SALT_SHA' ]"
ck "postgres 암호도 같다" bash -c "[ \"\$(sha256sum '$S/tokens/postgres-password' | cut -d' ' -f1)\" = '$PW_SHA' ]"
ck "kiosk-config 도 돌아왔다" test -s "$S/kiosk-config/e2e.json"
t "복구 뒤 권한 점검 통과" 0 bash "$HERE/check-secret-perms.sh" "$S"
t "비어 있지 않은 대상에는 덮어쓰지 않는다" 1 bash "$HERE/restore-secrets.sh" latest "$S" --yes
t "스냅샷 인자가 ID 형식이 아니면 거부" 1 bash "$HERE/restore-secrets.sh" "../x" "$T/dst3" --yes
echo; [ $F = 0 ] && echo "통과: 비밀 백업 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
