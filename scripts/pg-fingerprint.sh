#!/usr/bin/env bash
# PostgreSQL 데이터베이스의 논리 지문(스키마 + 행 집합의 해시). 행 순서와 무관하다. 복구 왕복 시험이 쓴다. 사용: pg-fingerprint.sh <데이터베이스>
# 서버가 떠 있어야 한다. 행 내용은 출력하지 않고 해시만 낸다. 환경: DEPLOY_PROJECT(기본 deploy)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
DB=${1:?데이터베이스}; [[ "$DB" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름 규칙 위반: $DB"
C=$(pg_container "${DEPLOY_PROJECT:-deploy}"); [ -n "$C" ] || die "postgres 컨테이너가 떠 있지 않다"
S=$("$DOCKER" exec "$C" pg_dump -U "$DB" -d "$DB" --schema-only --no-owner | grep -v '^--\|^\\restrict\|^\\unrestrict' | sha256sum | cut -c1-64)
R=$("$DOCKER" exec "$C" pg_dump -U "$DB" -d "$DB" --data-only --inserts --no-owner | grep '^INSERT' | sort | sha256sum | cut -c1-64)
N=$("$DOCKER" exec "$C" pg_dump -U "$DB" -d "$DB" --data-only --inserts --no-owner | grep -c '^INSERT' || true)
printf '{"database": "%s", "schema": "%s", "rows": "%s", "row_count": %s}\n' "$DB" "$S" "$R" "$N"
