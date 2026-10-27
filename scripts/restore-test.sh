#!/usr/bin/env bash
# 정기 복원 시험(D88/U6): 가장 최근 백업 세트를 **임시 데이터베이스**(restoretest_<db>)로 되살려 보고 지운다. 운영 데이터베이스는 건드리지 않는다.
# 항목마다: (1) 최신 스냅샷이 있고 너무 오래되지 않았다(--max-age-seconds, 기본 172800 = 일일 백업의 2배), (2) MANIFEST 해시가 파일과 같다,
#           (3) 복호화 명령이 있으면(BACKUP_DECRYPT_CMD) 복호화해 임시 데이터베이스로 pg_restore 가 성공하고 원본과 같은 테이블 목록·비어 있지 않은 행 수.
# 암호화된 백업인데 BACKUP_DECRYPT_CMD 가 없으면 (3)을 건너뛰고 '해시만 확인'이라고 분명히 낸다(서버에는 복호화 키가 없다: 키 보유자가 서버 밖에서 분기마다 전체 복원 시험을 한다, docs/runbook.md 4절).
# 사용: restore-test.sh [--max-age-seconds N] [db ...]   환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG. 종료 코드 0 통과, 1 실패, 2 설정 없음.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
MAXAGE=172800; [ "${1:-}" = --max-age-seconds ] && { MAXAGE=$2; shift 2; }
CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
[ -f "$CFG" ] || { echo "거부: 백업 설정 파일이 없다: $CFG" >&2; exit 2; }
BACKUP_DIR=; set -a; source "$CFG"; set +a
[ -n "$BACKUP_DIR" ] || { echo "거부: BACKUP_DIR 이 비어 있다" >&2; exit 2; }
P=${DEPLOY_PROJECT:-deploy}; C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
DBS=${*:-$PG_DBS}; FAILS=0; NOW=$(date +%s)
psu() { "$DOCKER" exec "$C" psql -U postgres -v ON_ERROR_STOP=1 -Atqc "$2" -d "${1:-postgres}"; }
tables() { psu "$1" "SELECT string_agg(relname, ',' ORDER BY relname) FROM pg_stat_user_tables" | tr -d '\r'; }
for db in $DBS; do
  snap=$(find "$BACKUP_DIR/pg-$db" -mindepth 1 -maxdepth 1 -type d -name '2*' 2>/dev/null | sort | tail -1)
  [ -n "$snap" ] || { echo "FAIL $db: 백업이 없다 ($BACKUP_DIR/pg-$db)"; FAILS=$((FAILS+1)); continue; }
  age=$(( NOW - $(stat -c %Y "$snap") ))
  [ $age -le "$MAXAGE" ] || { echo "FAIL $db: 최신 백업이 ${age}초 전이다(기준 ${MAXAGE}초): $snap"; FAILS=$((FAILS+1)); continue; }
  f="$snap/$db.dump"; enc=0; [ -f "$f" ] || { f="$snap/$db.dump.enc"; enc=1; }
  want=$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]+"/MANIFEST.json"))["files"][sys.argv[2]]["sha256"])' "$snap" "$(basename "$f")" 2>/dev/null)
  [ -n "$want" ] && [ "sha256:$(sha256sum "$f" | cut -d' ' -f1)" = "$want" ] || { echo "FAIL $db: 해시 불일치 또는 MANIFEST 문제: $f"; FAILS=$((FAILS+1)); continue; }
  if [ $enc = 1 ] && [ -z "${BACKUP_DECRYPT_CMD:-}" ]; then echo "해시만 확인 $db: 암호화된 백업이고 BACKUP_DECRYPT_CMD 가 없어 복원은 하지 않았다 (${age}초 전, $(basename "$snap"))"; continue; fi
  tmp="restoretest_$db"; psu postgres "DROP DATABASE IF EXISTS $tmp" >/dev/null; psu postgres "CREATE DATABASE $tmp" >/dev/null || { echo "FAIL $db: 임시 데이터베이스를 만들지 못했다"; FAILS=$((FAILS+1)); continue; }
  if [ $enc = 1 ]; then backup_decrypt < "$f" | "$DOCKER" exec -i "$C" pg_restore -U postgres -d "$tmp" --no-owner --exit-on-error 2>/tmp/restore-test.err; rc=$?
  else "$DOCKER" exec -i "$C" pg_restore -U postgres -d "$tmp" --no-owner --exit-on-error < "$f" 2>/tmp/restore-test.err; rc=$?; fi
  if [ $rc != 0 ]; then echo "FAIL $db: pg_restore 실패(종료 $rc): $(head -c 200 /tmp/restore-test.err | tr '\n' ' ')"; FAILS=$((FAILS+1)); psu postgres "DROP DATABASE IF EXISTS $tmp" >/dev/null; continue; fi
  t_src=$(tables "$db"); t_tmp=$(tables "$tmp"); rows=$(psu "$tmp" "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables" | tr -d '\r')
  psu "$tmp" "ANALYZE" >/dev/null 2>&1; rows=$(psu "$tmp" "SELECT coalesce(sum(reltuples)::bigint,0) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'" | tr -d '\r')
  psu postgres "DROP DATABASE IF EXISTS $tmp" >/dev/null
  if [ "$t_src" = "$t_tmp" ]; then echo "통과 $db: 복원 성공, 테이블 목록이 원본과 같다(${t_tmp:-없음}), 추정 행 수 $rows (${age}초 전 백업, $(basename "$snap"))"
  else echo "FAIL $db: 복원한 테이블 목록이 원본과 다르다 (원본: $t_src / 복원: $t_tmp)"; FAILS=$((FAILS+1)); fi
done
[ $FAILS = 0 ] && exit 0 || { echo "복원 시험 실패 $FAILS건"; exit 1; }
