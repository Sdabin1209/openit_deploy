#!/usr/bin/env bash
# 백업 필수화·암호화·복원 시험 자체 시험(서비스·E2E 없이 postgres 만). 사용: bash scripts/test-backup.sh
# 임시 프로젝트(deploy-bktest-*)에서 postgres 를 띄워 확인한다: 설정 없으면 CRIT(2), 개인키를 서버에 두면 거부, 암호화 백업(600/700, 평문 없음), 복호 후 복구,
# 파일 저장소(models-data)·레지스트리 볼륨 백업, 정기 복원 시험 스크립트. gpg 로 시험한다(age 가 있으면 age 도). 끝나면 모두 지운다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; P=deploy-bktest-$ID; W="$DEPLOY_ROOT/state/bktest-$ID"; mkdir -p "$W/backups"; chmod 700 "$W"
export DEPLOY_PROJECT=$P SECRETS_DIR="$W/secrets" DEPLOY_REGISTRY_ENV="$W/registry.env" REGISTRY_PROJECT=deploy-bkreg-$ID
echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$DEPLOY_REGISTRY_ENV"
cleanup() { dc "$P" down -v --remove-orphans >/dev/null 2>&1; "$DOCKER" volume rm -f "${REGISTRY_PROJECT}_registry-data" >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
FAILS=0; N=0
ok() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-220)"; FAILS=$((FAILS+1)); fi; }
rc() { N=$((N+1)); local name=$1 want=$2; shift 2; out=$("$@" 2>&1); local r=$?; if [ $r = "$want" ]; then echo "  PASS $name"; else echo "  FAIL $name :: 종료 $r (기대 $want) $(echo "$out" | tail -1 | cut -c1-200)"; FAILS=$((FAILS+1)); fi; }
C() { pg_container "$P"; }
echo "== 준비: 비밀, postgres, 시험용 gpg 키쌍(개인키는 서버가 아닌 임시 폴더, 시험 뒤 삭제)"
ok "gen-secrets.sh --db-only" bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --db-only "$SECRETS_DIR"
dc "$P" up -d --wait --wait-timeout 120 postgres >"$W/up.log" 2>&1; ok "postgres healthy" test -n "$(C)"
export GNUPGHOME="$W/gnupg"; mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --passphrase '' --quick-generate-key "openit-bktest" default default never >/dev/null 2>&1
gpg --batch --armor --export > "$W/recipient.pub" 2>/dev/null; gpg --batch --armor --export-secret-keys > "$W/private.asc" 2>/dev/null
for a in $PG_DBS; do "$DOCKER" exec "$(C)" psql -U "$a" -d "$a" -qc "CREATE TABLE items(id int PRIMARY KEY, v text); INSERT INTO items SELECT g, md5(g::text) FROM generate_series(1,500) g" >/dev/null 2>&1; done
fp() { bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" "$1"; }
cfg() { printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_ENCRYPT_RECIPIENTS=%s\nBACKUP_ENCRYPT_TOOL=gpg\n' "$W/backups" "$W/recipient.pub" > "$W/backup.env"; }
cfg; export BACKUP_CONFIG="$W/backup.env"
echo "== 설정이 없거나 불완전하면 CRIT 로 거부(종료 코드 2), init/doctor 점검도 막는다"
rc "설정 파일 없음 -> backup-all.sh 2" 2 env BACKUP_CONFIG="$W/none.env" bash "$DEPLOY_ROOT/scripts/backup-all.sh"
rc "설정 파일 없음 -> backup-check.sh 2" 2 env BACKUP_CONFIG="$W/none.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
printf 'BACKUP_DIR=\nBACKUP_RETENTION_DAYS=14\n' > "$W/b1.env";                   rc "BACKUP_DIR 비어 있음 -> 2" 2 env BACKUP_CONFIG="$W/b1.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=\n' "$W/backups" > "$W/b2.env";        rc "보관 일수 비어 있음 -> 2" 2 env BACKUP_CONFIG="$W/b2.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\n' "$W/backups" > "$W/b3.env";       rc "수신자 공개키 없음(암호화 없이는 거부) -> 2" 2 env BACKUP_CONFIG="$W/b3.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_ENCRYPT_RECIPIENTS=%s\nBACKUP_ENCRYPT_TOOL=gpg\n' "$W/backups" "$W/private.asc" > "$W/b4.env"
rc "수신자 파일에 개인키가 있으면 거부 -> 2" 2 env BACKUP_CONFIG="$W/b4.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_ALLOW_PLAINTEXT=1\n' "$W/backups" > "$W/b5.env"
rc "평문 허용(시험 전용)은 backup-check.sh 가 거부 -> 2" 2 env BACKUP_CONFIG="$W/b5.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
rc "올바른 설정은 backup-check.sh 통과" 0 bash "$DEPLOY_ROOT/scripts/backup-check.sh"
echo "== 암호화 백업"
for a in $PG_DBS; do eval "FP_$a=\$(fp $a)"; done
ok "pg-backup.sh (5개 병렬)" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
SN=$(ls -d "$W"/backups/pg-survey/2* | tail -1)
ok "스냅샷 폴더 700, 파일 600, 평문 덤프 없음, .gpg 있음" bash -c "[ \"\$(stat -c %a '$SN')\" = 700 ] && [ \"\$(stat -c %a '$SN/survey.dump.gpg')\" = 600 ] && [ \"\$(stat -c %a '$SN/MANIFEST.json')\" = 600 ] && [ ! -e '$SN/survey.dump' ] && [ \"\$(stat -c %a '$W/backups')\" = 700 ]"
ok "MANIFEST 에 평문 해시·암호화 파일 해시·덤프 시작/끝 시각" bash -c "grep -q '\"encryption\": \"gpg\"' '$SN/MANIFEST.json' && grep -q 'dump_started' '$SN/MANIFEST.json' && grep -q 'stored_file' '$SN/MANIFEST.json'"
ok "암호문에 평문 흔적(PGDMP 헤더)이 없다" bash -c "! head -c 64 '$SN/survey.dump.gpg' | grep -qa PGDMP"
rc "암호화된 스냅샷은 그대로 복구하면 거부하고 복호를 안내" 1 bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$SN" --yes
echo "== 복호(서버 밖 사람 몫 모사) -> 지운 뒤 복구 -> 지문 일치"
"$DOCKER" exec "$(C)" psql -U survey -d survey -qc "DELETE FROM items WHERE id % 2 = 0" >/dev/null 2>&1
rc "지운 뒤 지문이 달라졌다" 1 bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/pg-fingerprint.sh survey)\" = '$FP_survey' ]"
ok "개인키로 복호" gpg --batch --quiet --yes -o "$SN/survey.dump" -d "$SN/survey.dump.gpg"
ok "pg-restore.sh survey" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$SN" --yes
N=$((N+1)); if [ "$(fp survey)" = "$FP_survey" ]; then echo "  PASS 복구 후 행 지문 일치"; else echo "  FAIL 행 지문 불일치"; FAILS=$((FAILS+1)); fi
rm -f "$SN/survey.dump"
echo "== 파일 저장소: models-data, 레지스트리 볼륨(별도 프로젝트 이름)"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
if "$DOCKER" image inspect "$UTIL" >/dev/null 2>&1 || "$DOCKER" pull -q "$UTIL" >/dev/null 2>&1; then
  for v in "${P}_models-data" "${REGISTRY_PROJECT}_registry-data"; do "$DOCKER" volume create "$v" >/dev/null; "$DOCKER" run --rm -v "$v:/d" "$UTIL" sh -c "echo hello-$v > /d/f.txt"; done
  ok "backup.sh (기본 저장소: gate-data 는 볼륨이 없어 실패해야 하므로 두 저장소만 지정)" bash "$DEPLOY_ROOT/scripts/backup.sh" models-data registry-data
  S=$(ls -d "$W"/backups/models-data/2* | tail -1); R=$(ls -d "$W"/backups/registry-data/2* | tail -1)
  ok "tar 가 암호화되어 있고 600/700, 평문 f.txt 없음" bash -c "[ -f '$S/models-data.tar.gpg' ] && [ \"\$(stat -c %a '$S/models-data.tar.gpg')\" = 600 ] && [ \"\$(stat -c %a '$S')\" = 700 ] && [ -f '$R/registry-data.tar.gpg' ] && ! find '$S' '$R' -name f.txt | grep -q ."
  gpg --batch --quiet --yes -o "$S/models-data.tar" -d "$S/models-data.tar.gpg"
  "$DOCKER" run --rm -v "${P}_models-data:/d" "$UTIL" sh -c "rm -f /d/f.txt"
  ok "restore.sh models-data (복호한 tar)" bash "$DEPLOY_ROOT/scripts/restore.sh" models-data "$S" --yes
  ok "복구된 파일 내용" bash -c "[ \"\$('$DOCKER' run --rm -v ${P}_models-data:/d '$UTIL' cat /d/f.txt)\" = hello-${P}_models-data ]"
else echo "  SKIP 파일 저장소 시험: 유틸 이미지($UTIL)를 받지 못했다(확인 못 함, 통과 아님)"; fi
echo "== 정기 복원 시험 스크립트(시험용 키쌍으로 사슬 왕복 + 실제 백업 무결성)"
ok "backup-restore-test.sh" bash "$DEPLOY_ROOT/scripts/backup-restore-test.sh"
ok "임시 데이터베이스(rt_*)가 남지 않았다" bash -c "[ -z \"\$('$DOCKER' exec '$(C)' psql -U postgres -d postgres -Atqc \"SELECT datname FROM pg_database WHERE datname LIKE 'rt\\_%'\")\" ]"
printf 'x' >> "$SN/survey.dump.gpg"
rc "실제 백업 파일이 손상되면 복원 시험이 실패" 1 bash "$DEPLOY_ROOT/scripts/backup-restore-test.sh" survey
echo "== 암호화 실패 시 평문·partial 이 남지 않는다 (점검 M1)"
mkdir -p "$W/fakebin"; printf '#!/bin/sh\necho "가짜 gpg: 일부러 실패" >&2\nexit 2\n' > "$W/fakebin/gpg"; chmod +x "$W/fakebin/gpg"
"$DOCKER" volume create "${P}_models-data" >/dev/null 2>&1
rc "가짜 gpg 가 실패하면 backup.sh 도 비정상 종료" 1 env PATH="$W/fakebin:$PATH" bash "$DEPLOY_ROOT/scripts/backup.sh" models-data
N=$((N+1)); if ! ls -a "$W/backups/models-data" 2>/dev/null | grep -qE '^\.(tar|partial)-'; then echo "  PASS 실패 뒤 평문 .tar-* 와 .partial-* 가 남지 않았다"; else echo "  FAIL 임시 파일이 남았다: $(ls -a "$W/backups/models-data" | tr '\n' ' ')"; FAILS=$((FAILS+1)); fi
mkdir -p "$W/backups/models-data/.tar-OLD" ; touch -d '3 hours ago' "$W/backups/models-data/.tar-OLD"
( source "$DEPLOY_ROOT/scripts/lib.sh"; source "$DEPLOY_ROOT/scripts/backup-lib.sh"; BACKUP_RETENTION_DAYS=14; backup_prune "$W/backups/models-data" ) >/dev/null 2>&1
N=$((N+1)); if [ ! -e "$W/backups/models-data/.tar-OLD" ]; then echo "  PASS backup_prune 이 오래된 임시 파일(.tar-*)도 지운다"; else echo "  FAIL prune 이 임시 파일을 지우지 않았다"; FAILS=$((FAILS+1)); fi
echo "== gateway-data(내부 CA 루트·비밀키)도 암호화 백업된다 (점검 M3)"
"$DOCKER" volume create "${P}_gateway-data" >/dev/null 2>&1
UT=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
"$DOCKER" run --rm -v "${P}_gateway-data:/d" "$UT" sh -c 'mkdir -p /d/caddy/pki/authorities/local && echo FAKE-CA-PRIVATE-KEY-MARKER > /d/caddy/pki/authorities/local/root.key' >/dev/null 2>&1
ok "backup.sh gateway-data (암호화)" bash "$DEPLOY_ROOT/scripts/backup.sh" gateway-data
GD=$(ls -d "$W"/backups/gateway-data/2* | tail -1)
ok "gateway-data 백업은 암호문이고 평문 표지가 없다" bash -c "ls '$GD'/*.gpg >/dev/null && ! grep -aq FAKE-CA-PRIVATE-KEY-MARKER '$GD'/*"
ok "개인키(서버 밖)로 풀면 CA 비밀키 파일이 들어 있다(복원 시험)" bash -c "gpg --batch --quiet --decrypt '$GD'/gateway-data.tar.gpg 2>/dev/null | tar -tf - | grep -q 'caddy/pki/authorities/local/root.key'"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_ALLOW_PLAINTEXT=1\n' "$W/backups-plain" > "$W/bp.env"
N=$((N+1)); BACKUP_CONFIG="$W/bp.env" bash "$DEPLOY_ROOT/scripts/backup.sh" gateway-data >/dev/null 2>&1; if ! ls "$W"/backups-plain/gateway-data/2* >/dev/null 2>&1; then echo "  PASS 평문 모드에서는 CA 비밀키를 백업하지 않는다"; else echo "  FAIL 평문 모드에서 CA 비밀키가 백업됐다"; FAILS=$((FAILS+1)); fi
echo; [ $FAILS = 0 ] && echo "통과: 백업 자체 시험 $N건" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
