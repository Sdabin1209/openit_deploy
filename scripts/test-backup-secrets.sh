#!/usr/bin/env bash
# backup-secrets.sh / restore-secrets.sh 자체 시험(Docker 불필요, gpg 시험용 임시 키쌍). 사용: bash scripts/test-backup-secrets.sh
# 핵심: secrets/ 를 통째로 잃은 뒤 백업에서 되살리면 deid-salt 가 **같은 값으로** 돌아오는지. 값은 출력하지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); chmod 700 "$T"; trap 'rm -rf "$T"' EXIT
export GNUPGHOME="$T/gnupg"; mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --passphrase '' --quick-generate-key "openit-sectest" default default never >/dev/null 2>&1
gpg --batch --armor --export > "$T/recipient.pub" 2>/dev/null; gpg --batch --armor --export-secret-keys > "$T/private.asc" 2>/dev/null
N=0; F=0
t() { local name=$1 want=$2; shift 2; N=$((N+1)); out=$("$@" 2>&1); local rc=$?; if [ $rc = "$want" ]; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want) $(echo "$out" | tail -1 | cut -c1-160)"; F=$((F+1)); fi; }
ck() { N=$((N+1)); local name=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; F=$((F+1)); fi; }
S="$T/secrets"; bash "$HERE/gen-secrets.sh" --db-only "$S" >/dev/null 2>&1
python3 -c 'import secrets;print(secrets.token_hex(24))' > "$S/tokens/deid-salt"; chmod 644 "$S/tokens/deid-salt"
mkdir -p "$S/kiosk-config"; echo '{"device_token":"x"}' > "$S/kiosk-config/e2e.json"
SALT_SHA=$(sha256sum "$S/tokens/deid-salt" | cut -d' ' -f1); PW_SHA=$(sha256sum "$S/tokens/postgres-password" | cut -d' ' -f1)
SALT=$(cat "$S/tokens/deid-salt")
printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_ENCRYPT_RECIPIENTS=%s\nBACKUP_ENCRYPT_TOOL=gpg\nBACKUP_SECRETS_KEEP=2\n' "$T" "$T/recipient.pub" > "$T/backup.env"
export BACKUP_CONFIG="$T/backup.env" SECRETS_DIR="$S"
t "백업 성공" 0 bash "$HERE/backup-secrets.sh"
SN=$(ls -d "$T"/bk/secrets/2* | tail -1)
ck "암호문 파일 600, 폴더 700, 평문 tar 없음" bash -c "[ \"\$(stat -c %a '$SN/secrets.tar.gpg')\" = 600 ] && [ \"\$(stat -c %a '$SN')\" = 700 ] && [ ! -e '$SN/secrets.tar' ] && [ \"\$(stat -c %a '$T/bk/secrets')\" = 700 ]"
ck "암호문에 salt 값이 없다" bash -c "! grep -qaF '$SALT' '$SN/secrets.tar.gpg'"
ck "MANIFEST 에 salt 값이 없다(파일 수·해시만)" bash -c "! grep -qF '$SALT' '$SN/MANIFEST.json' && grep -q stored_file '$SN/MANIFEST.json'"
t "백업 출력에 salt 값이 없다" 1 bash -c "bash '$HERE/backup-secrets.sh' | grep -F '$SALT'"
sleep 1; bash "$HERE/backup-secrets.sh" >/dev/null 2>&1; sleep 1; bash "$HERE/backup-secrets.sh" >/dev/null 2>&1
ck "보존: 최신 2개만 남는다" bash -c "[ \$(ls -d '$T'/bk/secrets/2* | wc -l) = 2 ]"
printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_ALLOW_PLAINTEXT=1\n' "$T" > "$T/plain.env"
t "평문 모드는 거부(2)" 2 env BACKUP_CONFIG="$T/plain.env" bash "$HERE/backup-secrets.sh"
t "설정 없으면 CRIT(2)" 2 env BACKUP_CONFIG="$T/none.env" bash "$HERE/backup-secrets.sh"
printf 'BACKUP_DIR=%s/bk\nBACKUP_RETENTION_DAYS=14\nBACKUP_ENCRYPT_RECIPIENTS=%s\nBACKUP_ENCRYPT_TOOL=gpg\nBACKUP_SECRETS_DIR=%s/elsewhere\n' "$T" "$T/recipient.pub" "$T" > "$T/alt.env"
t "BACKUP_SECRETS_DIR 로 다른 곳에 둔다" 0 env BACKUP_CONFIG="$T/alt.env" bash "$HERE/backup-secrets.sh"
ck "다른 대상 폴더에 생겼다" bash -c "ls -d '$T'/elsewhere/2* >/dev/null"
echo "== 분실 시나리오: secrets/ 를 통째로 지운다 -> 개인키로 복호 -> 복구"
SN=$(ls -d "$T"/bk/secrets/2* | tail -1); rm -rf "$S"
ck "salt 가 없어졌다" test ! -e "$S/tokens/deid-salt"
ck "개인키 없이는 못 푼다(다른 홈에서 복호 실패)" bash -c "! GNUPGHOME=\$(mktemp -d) gpg --batch --quiet -d '$SN/secrets.tar.gpg' >/dev/null 2>&1"
gpg --batch --quiet --yes -o "$T/secrets.tar" -d "$SN/secrets.tar.gpg" 2>/dev/null
t "restore-secrets.sh" 0 bash "$HERE/restore-secrets.sh" "$T/secrets.tar" "$S" --yes
ck "deid-salt 가 같은 값으로 돌아왔다" bash -c "[ \"\$(sha256sum '$S/tokens/deid-salt' | cut -d' ' -f1)\" = '$SALT_SHA' ]"
ck "postgres 암호도 같다" bash -c "[ \"\$(sha256sum '$S/tokens/postgres-password' | cut -d' ' -f1)\" = '$PW_SHA' ]"
ck "kiosk-config 도 돌아왔다" test -s "$S/kiosk-config/e2e.json"
t "복구 뒤 권한 점검 통과" 0 bash "$HERE/check-secret-perms.sh" "$S"
t "비어 있지 않은 대상에는 덮어쓰지 않는다" 1 bash "$HERE/restore-secrets.sh" "$T/secrets.tar" "$S" --yes
tar -cf "$T/evil.tar" -P --transform='s|^|../|' "$T/restore-evil" 2>/dev/null; echo x > "$T/e.txt"; tar -cf "$T/evil.tar" --transform='s|^|../|' -C "$T" e.txt
t "상위 경로(..) tar 는 거부" 1 bash "$HERE/restore-secrets.sh" "$T/evil.tar" "$T/dst2" --yes
echo; [ $F = 0 ] && echo "통과: 비밀 백업 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
