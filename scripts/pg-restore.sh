#!/usr/bin/env bash
# PostgreSQL 복구. 사용: pg-restore.sh <데이터베이스> <latest|스냅샷 ID> --yes     환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG
# 그 데이터베이스를 쓰는 서비스가 멈춰 있어야 한다(다른 접속이 있으면 거부). restic dump 가 스냅샷의 덤프를 평문으로 디스크에 쓰지 않고 pg_restore 에 바로 흘린다.
# 데이터베이스의 객체를 지우고(--clean) 한 트랜잭션으로 되살린다. 서버·데이터베이스·계정은 이미 있어야 한다(새 볼륨이면 postgres 서비스를 먼저 띄우면 초기화 스크립트가 만든다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
DB=${1:?데이터베이스}; SNAP=$(backup_snapshot_arg "${2:?스냅샷(latest 또는 ID)}"); [ "${3:-}" = "--yes" ] || die "--yes 가 필요하다(데이터베이스의 현재 내용을 지운다)"
[[ "$DB" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $DB"
BACKUP_CHECK_ONLY=1 backup_load_config
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
OTHERS=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$DB' AND pid <> pg_backend_pid()" | tr -d '\r')
[ "$OTHERS" = 0 ] || die "$DB 에 다른 접속이 $OTHERS 개 있다. 이 데이터베이스를 쓰는 서비스를 먼저 멈춘다"
backup_restic -- dump "$SNAP" "/$DB.dump" --host "pg-$DB" | "$DOCKER" exec -i "$C" pg_restore -U "$DB" -d "$DB" --clean --if-exists --no-owner --single-transaction --exit-on-error
echo "복구: $DB <- restic 스냅샷 $SNAP"
