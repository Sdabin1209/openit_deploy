#!/usr/bin/env bash
# 정기 복원 시험(systemd 잡 backup-restore-test, 주 1회). 사용: backup-restore-test.sh [데이터베이스 ...]   환경: DEPLOY_PROJECT(기본 deploy)
# 백업은 복원해 보기 전에는 백업이 아니다(D88 U6). 두 가지를 한다.
#  1) 도구 사슬 왕복(실제 저장소와 무관): 임시 암호·임시 restic 저장소를 만들어 현재 운영 데이터를 pg-backup.sh 로 백업 -> restic dump 로 임시 데이터베이스(rt_*)에
#     pg_restore -> 원본과 행 지문(스키마 해시 + 정렬한 INSERT 행 해시 + 행 수)을 대조. 운영 데이터베이스는 읽기만 한다. 끝나면 임시 DB·저장소를 지운다.
#     원본이 시험 중에 바뀌면 지문이 어긋날 수 있어 최대 3번 다시 한다(그래도 다르면 FAIL).
#  2) 실제 저장소 무결성: BACKUP_DIR 의 restic 저장소에서 데이터베이스마다 스냅샷이 있는지 보고, restic check --read-data-subset 으로 저장소 구조와 데이터 일부를 다시 읽어 검증한다.
#     (restic 은 모든 블롭을 해시·인증하므로 읽으면 손상이 드러난다. 일부만 읽는 이유: 매주 전체를 읽으면 원격 대상에서 비용이 크다. 5% 는 시작값, 측정 안 함, ADR 0038.)
# 실제 암호로 사람이 서버 밖에서 처음부터 복원하는 시험은 분기마다 한다(docs/runbook.md 4절). 이 시험은 그것을 대신하지 않는다.
# 종료 코드: 0 통과, 1 시험 실패(복원 사슬이 깨졌거나 지문 불일치), 2 설정 문제(CRIT). systemd 서비스 결과가 job-metrics.sh 로 지표가 된다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
P=${DEPLOY_PROJECT:-deploy}; DBS=${*:-$PG_DBS}
CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
[ -f "$CFG" ] || { echo "CRIT: 백업 설정 파일이 없다: $CFG" >&2; exit 2; }
( BACKUP_CHECK_ONLY=1; BACKUP_CONFIG=$CFG; backup_load_config ) || exit 2
C=$(pg_container "$P"); [ -n "$C" ] || { echo "FAIL: 프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다" >&2; exit 1; }
T=$(mktemp -d); chmod 700 "$T"; RT=""
cleanup() { for d in $RT; do "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "DROP DATABASE IF EXISTS $d" >/dev/null 2>&1; done; rm -rf "$T"; }
trap cleanup EXIT
FAILS=0; fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS+1)); }

# 임시 암호(시험 전용, 임시 폴더 안, 끝나면 지워진다)와 임시 저장소 위치
( umask 077; head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$T/pw" )
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=1\nBACKUP_PASSWORD_FILE=%s\n' "$T/out" "$T/pw" > "$T/backup.env"

fp() { # fp <컨테이너 안 접속 계정> <db>: 스키마 해시 + 행 해시 + 행 수 (pg-fingerprint.sh 와 같은 방식, 행 내용은 출력하지 않는다)
  local u=$1 db=$2 s r n
  s=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --schema-only --no-owner --no-acl | grep -v '^--\|^\\restrict\|^\\unrestrict' | sha256sum | cut -c1-64)
  r=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --data-only --inserts --no-owner | { grep '^INSERT' || true; } | sort | sha256sum | cut -c1-64)
  n=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --data-only --inserts --no-owner | { grep -c '^INSERT' || true; })
  echo "$s $r $n"
}
restore_into() { # restore_into <db> <임시 db>: 임시 저장소의 최신 덤프를 임시 데이터베이스로 되살린다
  ( BACKUP_CONFIG="$T/backup.env"; BACKUP_CHECK_ONLY=1; backup_load_config; backup_restic -- dump latest "/$1.dump" --host "pg-$1" ) \
    | "$DOCKER" exec -i "$C" pg_restore -U postgres -d "$2" --no-owner --exit-on-error --single-transaction >/dev/null 2>"$T/err"
}
echo "== 1) 도구 사슬 왕복 (restic, 임시 암호·임시 저장소, 임시 데이터베이스)"
for db in $DBS; do
  ok=0
  for try in 1 2 3; do
    before=$(fp "$db" "$db")
    BACKUP_CONFIG="$T/backup.env" DEPLOY_PROJECT="$P" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" "$db" >/dev/null 2>"$T/err" || { fail "$db 백업 실패: $(tail -1 "$T/err")"; break; }
    rt="rt_${db}_$$"; RT="$RT $rt"
    "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "CREATE DATABASE $rt" >/dev/null 2>&1 || { fail "$db 임시 데이터베이스를 만들지 못했다"; break; }
    restore_into "$db" "$rt" || { fail "$db 복원(restic dump | pg_restore) 실패: $(tail -1 "$T/err")"; break; }
    after=$(fp "$db" "$db"); got=$(fp postgres "$rt")
    if [ "$before" = "$after" ] && [ "$got" = "$before" ]; then ok=1; echo "  PASS $db: 행 지문 일치 (행 수 ${got##* })"; break; fi
    if [ "$before" != "$after" ]; then echo "  재시도 $try/3: $db 원본이 시험 중에 바뀌었다"; "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "DROP DATABASE $rt" >/dev/null 2>&1; continue; fi
    fail "$db 복원본의 행 지문이 원본과 다르다 (원본 ${before##* }행, 복원본 ${got##* }행)"; break
  done
  [ $ok = 1 ] || { [ $FAILS -gt 0 ] || fail "$db 원본이 계속 바뀌어 대조하지 못했다(3회)"; }
done
echo "== 2) 실제 저장소 무결성 (restic check, 암호 파일로 읽는다)"
n=0
( BACKUP_CONFIG="$CFG"; BACKUP_CHECK_ONLY=1; backup_load_config
  backup_restic -- cat config >/dev/null 2>&1 || { echo "FAIL: 실제 restic 저장소를 열 수 없다(없거나 닿지 못하거나 암호가 틀림): ${BACKUP_REPOSITORY:-$BACKUP_DIR/restic}" >&2; exit 1; }
  rc=0
  for db in $DBS; do
    cnt=$(backup_restic -- snapshots --host "pg-$db" --json 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin) or []))' 2>/dev/null || echo 0)
    if [ "${cnt:-0}" -ge 1 ]; then echo "  PASS $db: 스냅샷 ${cnt}개"; else echo "FAIL: $db 실제 백업(스냅샷)이 없다" >&2; rc=1; fi
  done
  if [ "${RESTIC_CHECK_FULL:-0}" = 1 ]; then chk=(--read-data); lab="전체"; else chk=(--read-data-subset=5%); lab="5%"; fi   # RESTIC_CHECK_FULL=1 은 시험 전용(작은 저장소의 손상을 확실히 잡는다)
  backup_restic -- check "${chk[@]}" >"$T/check.out" 2>&1 && echo "  PASS restic check ($lab 읽음)" || { echo "FAIL: restic check: $(tail -2 "$T/check.out" | tr '\n' ' ')" >&2; rc=1; }
  exit $rc ) || FAILS=$((FAILS+1))
[ $FAILS = 0 ] && { echo "통과: 복원 시험 (도구 사슬 $(echo $DBS | wc -w)개, 실제 저장소 무결성)"; exit 0; } || { echo "실패: $FAILS건" >&2; exit 1; }
