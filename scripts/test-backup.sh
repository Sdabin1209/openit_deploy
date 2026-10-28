#!/usr/bin/env bash
# 백업 필수화·암호화·복원 자체 시험(서비스·E2E 없이 postgres 만). 사용: bash scripts/test-backup.sh   (Docker 필요: restic 은 digest 고정 이미지로 돈다, ADR 0038)
# 임시 프로젝트(deploy-bktest-*)에서 postgres 를 띄워 확인한다: 설정 없으면 CRIT(2), 옛 키·암호 파일 문제 거부, 암호화 백업(저장소에 평문 없음), 지운 뒤 복구,
# 파일 저장소(models-data)·레지스트리·gateway-data 볼륨 백업·복구, 중도 실패한 덤프가 성공으로 남지 않음, 보관 기간 정리, 정기 복원 시험 스크립트. 끝나면 모두 지운다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; P=deploy-bktest-$ID; W="$DEPLOY_ROOT/state/bktest-$ID"; mkdir -p "$W/backups"; chmod 700 "$W"
export DEPLOY_PROJECT=$P SECRETS_DIR="$W/secrets" DEPLOY_REGISTRY_ENV="$W/registry.env" REGISTRY_PROJECT=deploy-bkreg-$ID
echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$DEPLOY_REGISTRY_ENV"
source "$(dirname "$0")/testlib.sh"; test_lock_copy "$W/images.lock"; export DEPLOY_LOCK="$W/images.lock"   # 커밋된 잠금이 불완전해도 compose 가 해석되게(scripts/testlib.sh)
# 백업 파일은 root 컨테이너가 만든다: 지울 때도 root 권한이 필요할 수 있어 호스트 사용자 소유로 되돌린 뒤 지운다
cleanup() { dc "$P" down -v --remove-orphans >/dev/null 2>&1; "$DOCKER" volume rm -f "${REGISTRY_PROJECT}_registry-data" >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
FAILS=0; N=0
ok() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-220)"; FAILS=$((FAILS+1)); fi; }
rc() { N=$((N+1)); local name=$1 want=$2; shift 2; out=$("$@" 2>&1); local r=$?; if [ $r = "$want" ]; then echo "  PASS $name"; else echo "  FAIL $name :: 종료 $r (기대 $want) $(echo "$out" | tail -1 | cut -c1-200)"; FAILS=$((FAILS+1)); fi; }
C() { pg_container "$P"; }
echo "== 준비: 비밀, postgres, 시험용 restic 암호 파일(시험 폴더 안, 시험 뒤 삭제)"
ok "gen-secrets.sh --db-only" bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --db-only "$SECRETS_DIR"
dc "$P" up -d --wait --wait-timeout 120 postgres >"$W/up.log" 2>&1; ok "postgres healthy" test -n "$(C)"
( umask 077; echo "bktest-password-$ID-not-a-secret" > "$W/backup.pass" )
for a in $PG_DBS; do "$DOCKER" exec "$(C)" psql -U "$a" -d "$a" -qc "CREATE TABLE items(id int PRIMARY KEY, v text); INSERT INTO items SELECT g, md5(g::text) FROM generate_series(1,500) g" >/dev/null 2>&1; done
fp() { bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" "$1"; }
cfg() { printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backup.pass" > "$W/backup.env"; }
cfg; export BACKUP_CONFIG="$W/backup.env"
echo "== 설정이 없거나 불완전하면 CRIT 로 거부(종료 코드 2), init/doctor 점검도 막는다"
rc "설정 파일 없음 -> backup-all.sh 2" 2 env BACKUP_CONFIG="$W/none.env" bash "$DEPLOY_ROOT/scripts/backup-all.sh"
rc "설정 파일 없음 -> backup-check.sh 2" 2 env BACKUP_CONFIG="$W/none.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
printf 'BACKUP_DIR=\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$W/backup.pass" > "$W/b1.env";   rc "BACKUP_DIR 비어 있음 -> 2" 2 env BACKUP_CONFIG="$W/b1.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backup.pass" > "$W/b2.env";   rc "보관 일수 비어 있음 -> 2" 2 env BACKUP_CONFIG="$W/b2.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\n' "$W/backups" > "$W/b3.env";       rc "암호 파일 없음(암호화 없이는 거부) -> 2" 2 env BACKUP_CONFIG="$W/b3.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
( umask 022; echo x > "$W/loose.pass" ); chmod 644 "$W/loose.pass"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/loose.pass" > "$W/b4.env"
rc "암호 파일 모드가 644 면 거부 -> 2" 2 env BACKUP_CONFIG="$W/b4.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
mkdir -p "$W/backups/inside"; ( umask 077; echo x > "$W/backups/inside/pw" )
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backups/inside/pw" > "$W/b5.env"
rc "암호 파일이 BACKUP_DIR 안에 있으면 거부 -> 2" 2 env BACKUP_CONFIG="$W/b5.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_ALLOW_PLAINTEXT=1\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backup.pass" > "$W/b6.env"
rc "옛 키(BACKUP_ALLOW_PLAINTEXT)가 남아 있으면 거부 -> 2" 2 env BACKUP_CONFIG="$W/b6.env" bash "$DEPLOY_ROOT/scripts/backup-check.sh"
rc "올바른 설정은 backup-check.sh 통과" 0 bash "$DEPLOY_ROOT/scripts/backup-check.sh"
echo "== 암호화 백업"
for a in $PG_DBS; do eval "FP_$a=\$(fp $a)"; done
ok "pg-backup.sh (5개 병렬)" bash "$DEPLOY_ROOT/scripts/pg-backup.sh"
ok "restic 저장소가 만들어졌고 모드 700 폴더 안이다" bash -c "[ -f '$W/backups/restic/config' ] && [ \"\$(stat -c %a '$W/backups')\" = 700 ]"
ok "저장소 파일에 덤프 평문 표지(PGDMP)나 테이블 이름이 없다(암호화됨)" bash -c "! grep -rqa 'PGDMP\|CREATE TABLE' '$W/backups/restic'"
ok "스냅샷이 데이터베이스마다 하나(host pg-<db>)이고 같은 set 태그를 가진다" bash -c "n=\$(bash -c 'source $DEPLOY_ROOT/scripts/lib.sh; source $DEPLOY_ROOT/scripts/backup-lib.sh; backup_load_config; backup_restic -- snapshots --json' | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d), len({t for s in d for t in s[\"tags\"] if t.startswith(\"set-\")}))'); [ \"\$n\" = '5 1' ]"
echo "== 지운 뒤 복구 -> 지문 일치 (평문 덤프는 디스크에 쓰이지 않는다)"
"$DOCKER" exec "$(C)" psql -U survey -d survey -qc "DELETE FROM items WHERE id % 2 = 0" >/dev/null 2>&1
rc "지운 뒤 지문이 달라졌다" 1 bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/pg-fingerprint.sh survey)\" = '$FP_survey' ]"
rc "스냅샷 ID 형식이 아니면 거부" 1 bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "../x" --yes
ok "pg-restore.sh survey latest" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey latest --yes
N=$((N+1)); if [ "$(fp survey)" = "$FP_survey" ]; then echo "  PASS 복구 후 행 지문 일치"; else echo "  FAIL 행 지문 불일치"; FAILS=$((FAILS+1)); fi
echo "== 잘못된 암호로는 저장소를 못 연다"
( umask 077; echo wrong-password > "$W/wrong.pass" ); printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=14\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/wrong.pass" > "$W/bw.env"
rc "틀린 암호로 복구하면 실패한다" 1 env BACKUP_CONFIG="$W/bw.env" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey latest --yes
echo "== 파일 저장소: models-data, 레지스트리 볼륨(별도 프로젝트 이름)"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
if "$DOCKER" image inspect "$UTIL" >/dev/null 2>&1 || "$DOCKER" pull -q "$UTIL" >/dev/null 2>&1; then
  for v in "${P}_models-data" "${REGISTRY_PROJECT}_registry-data"; do "$DOCKER" volume create "$v" >/dev/null; "$DOCKER" run --rm -v "$v:/d" "$UTIL" sh -c "echo hello-$v > /d/f.txt; chown 10001:10001 /d/f.txt; chmod 600 /d/f.txt"; done
  ok "backup.sh (기본 저장소: gate-data 는 볼륨이 없어 실패해야 하므로 두 저장소만 지정)" bash "$DEPLOY_ROOT/scripts/backup.sh" models-data registry-data
  ok "저장소 파일 소유자가 호스트 사용자다(root 로 쓴 파일을 되돌렸다)" bash -c "[ -z \"\$(find '$W/backups/restic' ! -user $(id -u) | head -1)\" ]"
  ok "저장소에 평문 표지(hello-)가 없다" bash -c "! grep -rqa 'hello-' '$W/backups/restic'"
  "$DOCKER" run --rm -v "${P}_models-data:/d" "$UTIL" sh -c "rm -f /d/f.txt"
  rc "서비스가 볼륨을 쓰는 동안은 거부" 1 bash -c "docker run -d --name bkuse-$ID -v ${P}_models-data:/d $UTIL sleep 60 >/dev/null; bash $DEPLOY_ROOT/scripts/restore.sh models-data latest --yes; r=\$?; docker rm -f bkuse-$ID >/dev/null; exit \$r"
  ok "restore.sh models-data latest" bash "$DEPLOY_ROOT/scripts/restore.sh" models-data latest --yes
  ok "복구된 파일 내용" bash -c "[ \"\$('$DOCKER' run --rm -v ${P}_models-data:/d '$UTIL' cat /d/f.txt)\" = hello-${P}_models-data ]"
  ok "복구된 파일의 소유자·모드가 백업 때와 같다(10001, 600)" bash -c "[ \"\$('$DOCKER' run --rm -v ${P}_models-data:/d '$UTIL' stat -c '%u:%a' /d/f.txt)\" = 10001:600 ]"
else echo "  SKIP 파일 저장소 시험: 유틸 이미지($UTIL)를 받지 못했다(확인 못 함, 통과 아님)"; fi
echo "== 정기 복원 시험 스크립트(임시 저장소로 사슬 왕복 + 실제 저장소 무결성)"
ok "backup-restore-test.sh" bash "$DEPLOY_ROOT/scripts/backup-restore-test.sh"
ok "임시 데이터베이스(rt_*)가 남지 않았다" bash -c "[ -z \"\$('$DOCKER' exec '$(C)' psql -U postgres -d postgres -Atqc \"SELECT datname FROM pg_database WHERE datname LIKE 'rt\\_%'\")\" ]"
echo "== 저장소가 손상되면 복원 시험이 실패한다"
cp -r "$W/backups/restic" "$W/restic.good"
f=$(find "$W/backups/restic/data" -type f | head -1); chmod u+w "$f"; printf 'x' >> "$f"   # restic 은 데이터 파일을 0400 으로 쓴다
rc "실제 저장소의 데이터 파일이 손상되면 복원 시험이 실패(restic check)" 1 env RESTIC_CHECK_FULL=1 bash "$DEPLOY_ROOT/scripts/backup-restore-test.sh" survey
rm -rf "$W/backups/restic"; cp -r "$W/restic.good" "$W/backups/restic"
echo "== 덤프가 중간에 실패하면 불완전한 스냅샷이 성공으로 남지 않는다 (옛 점검 M1 의 restic 판)"
n0=$(bash -c "source $DEPLOY_ROOT/scripts/lib.sh; source $DEPLOY_ROOT/scripts/backup-lib.sh; backup_load_config; backup_restic -- snapshots --json" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')
rc "없는 데이터베이스를 지정하면 pg-backup.sh 가 실패" 1 bash "$DEPLOY_ROOT/scripts/pg-backup.sh" survey nosuchdb
n1=$(bash -c "source $DEPLOY_ROOT/scripts/lib.sh; source $DEPLOY_ROOT/scripts/backup-lib.sh; backup_load_config; backup_restic -- snapshots --json" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')
N=$((N+1)); if [ "$n0" = "$n1" ]; then echo "  PASS 실패한 실행의 스냅샷(부분 결과 포함)이 남지 않았다 ($n0 -> $n1)"; else echo "  FAIL 스냅샷 수가 달라졌다 ($n0 -> $n1)"; FAILS=$((FAILS+1)); fi
echo "== 보관 기간: 오래된 스냅샷만 지우고 저장소(host)마다 가장 최근 하나는 남긴다"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=0\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backup.pass" > "$W/b0.env"
ok "보관 0일: 저장소마다 최신 하나만 남는다" bash -c "BACKUP_CONFIG='$W/b0.env' bash $DEPLOY_ROOT/scripts/pg-backup.sh survey >/dev/null && BACKUP_CONFIG='$W/b0.env' bash -c 'source $DEPLOY_ROOT/scripts/lib.sh; source $DEPLOY_ROOT/scripts/backup-lib.sh; backup_load_config; backup_restic -- snapshots --host pg-survey --json' | python3 -c 'import json,sys;sys.exit(0 if len(json.load(sys.stdin))==1 else 1)'"
echo "== gateway-data(내부 CA 루트·비밀키)도 암호화 백업된다 (점검 M3)"
"$DOCKER" volume create "${P}_gateway-data" >/dev/null 2>&1
"$DOCKER" run --rm -v "${P}_gateway-data:/d" "$UTIL" sh -c 'mkdir -p /d/caddy/pki/authorities/local && echo FAKE-CA-PRIVATE-KEY-MARKER > /d/caddy/pki/authorities/local/root.key && chown -R 10001:10001 /d && chmod 600 /d/caddy/pki/authorities/local/root.key' >/dev/null 2>&1
ok "backup.sh gateway-data (uid 10001 소유 0600 파일도 읽는다)" bash "$DEPLOY_ROOT/scripts/backup.sh" gateway-data
ok "저장소에 CA 비밀키 평문 표지가 없다" bash -c "! grep -rqa FAKE-CA-PRIVATE-KEY-MARKER '$W/backups/restic'"
"$DOCKER" run --rm -v "${P}_gateway-data:/d" "$UTIL" sh -c 'rm -rf /d/caddy'
ok "restore.sh gateway-data 로 CA 비밀키 파일이 돌아온다" bash -c "bash $DEPLOY_ROOT/scripts/restore.sh gateway-data latest --yes >/dev/null && $DOCKER run --rm -v ${P}_gateway-data:/d $UTIL cat /d/caddy/pki/authorities/local/root.key | grep -q FAKE-CA-PRIVATE-KEY-MARKER"
# 겹침 실행 방지(점검 M4): 다른 백업이 BACKUP_DIR 잠금을 쥐고 있으면 거부(종료 4)한다.
exec 8>"$W/backups/.backup.lock"; flock -n 8
rc "백업이 진행 중이면(잠금) 두 번째 backup.sh 는 거부 4" 4 bash "$DEPLOY_ROOT/scripts/backup.sh" models-data
flock -u 8; exec 8>&-
ok "잠금을 놓으면 다시 백업된다" bash "$DEPLOY_ROOT/scripts/backup.sh" models-data
echo; [ $FAILS = 0 ] && echo "통과: 백업 자체 시험 $N건" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
