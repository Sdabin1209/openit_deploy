#!/bin/bash
# 서비스마다 데이터베이스 하나와 그 데이터베이스만 쓰는 계정 하나를 만든다. 공식 이미지의 /docker-entrypoint-initdb.d 에서 처음 한 번 돌고,
# 멱등이라 실행 중인 서버에 다시 돌려도 된다(scripts/pg-roles.sh sync: 계정 추가·암호 교체).
# 계정 암호는 비밀 파일(/run/secrets/db-<이름>-password, 이름의 _ 는 -)에서 읽는다. 값은 인자·환경 변수·출력에 나오지 않는다(psql 의 \set ... `cat` 으로 읽는다).
# 권한: 계정은 자기 데이터베이스의 소유자(스키마 변경 가능)이고 슈퍼유저·DB 생성·역할 생성·복제 권한이 없다.
#       PUBLIC 의 CONNECT 를 모두 거두어 다른 계정의 데이터베이스와 postgres·template1 에는 접속할 수 없다.
# 환경: PG_ROLE_CONN_LIMIT(계정별 연결 상한, 기본 20), PG_INIT_ACCOUNTS(공백으로 나눈 이름, 기본 survey qa ops_log ops_failure gate), PG_INIT_SECRETS_DIR(기본 /run/secrets), POSTGRES_USER(기본 postgres)
set -Eeuo pipefail
ACCOUNTS=${PG_INIT_ACCOUNTS:-"survey qa ops_log ops_failure gate"}
SDIR=${PG_INIT_SECRETS_DIR:-/run/secrets}
# 계정별 동시 연결 상한: 한 서비스의 연결 폭주가 다른 서비스를 막지 않게 한다. 값은 측정 안 함(시작값, docs/adr/0024-postgres-logging-and-limits.md). PG_ROLE_CONN_LIMIT 로 바꾼다.
LIMIT=${PG_ROLE_CONN_LIMIT:-20}
[[ "$LIMIT" =~ ^[0-9]+$ ]] || { echo "10-roles: PG_ROLE_CONN_LIMIT 가 정수가 아니다: '$LIMIT'" >&2; exit 1; }
psql_() { psql -v ON_ERROR_STOP=1 --no-psqlrc -X -q -U "${POSTGRES_USER:-postgres}" -d postgres "$@"; }

for acc in $ACCOUNTS; do
  [[ "$acc" =~ ^[a-z][a-z0-9_]{0,30}$ ]] || { echo "10-roles: 계정 이름이 규칙에 맞지 않는다: '$acc'" >&2; exit 1; }
  pwfile="$SDIR/db-${acc//_/-}-password"
  [ -s "$pwfile" ] || { echo "10-roles: 암호 파일이 없거나 비었다: $pwfile" >&2; exit 1; }
  PWFILE="$pwfile" psql_ -v acc="$acc" -v limit="$LIMIT" <<'SQL'
\set pw `cat "$PWFILE"`
SELECT format('CREATE ROLE %I', :'acc') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'acc') \gexec
ALTER ROLE :"acc" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT :limit PASSWORD :'pw';
SELECT format('CREATE DATABASE %I OWNER %I', :'acc', :'acc') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'acc') \gexec
ALTER DATABASE :"acc" OWNER TO :"acc";
REVOKE ALL ON DATABASE :"acc" FROM PUBLIC;
GRANT ALL ON DATABASE :"acc" TO :"acc";
SQL
  echo "10-roles: 데이터베이스·계정 준비됨: $acc"
done
# pg_hba.conf: 공식 이미지는 루프백(127.0.0.1, ::1) TCP 에도 trust 를 둔다. 암호 없이 들어오는 길은 컨테이너 안의 유닉스 소켓(docker exec 로만 닿는다)만 남기고
# 루프백 TCP 도 암호(scram-sha-256)를 요구하게 바꾼다. 복제(replication) 줄의 루프백 trust 도 같이 바꾼다(pg-config-check.sh 가 찾아낸 빈틈: 예전에는 all 줄만 바꿨다). 이미 바뀌었으면 아무것도 하지 않는다(멱등).
HBA=$(psql_ -Atc 'SHOW hba_file')
sed -i -E 's#^(host[[:space:]]+(all|replication)[[:space:]]+all[[:space:]]+(127\.0\.0\.1/32|::1/128)[[:space:]]+)trust#\1scram-sha-256#' "$HBA"
# 최초 초기화의 임시 서버(listen_addresses 가 비어 있다)는 곧 꺼지고 본 서버가 파일을 새로 읽으므로 다시 읽히지 않는다(불필요한 경고를 피한다)
[ -z "$(psql_ -Atc 'SHOW listen_addresses')" ] || psql_ -Atc 'SELECT pg_reload_conf()' >/dev/null
# 기본 데이터베이스에는 서비스 계정이 들어오지 못하게 한다(슈퍼유저는 소켓으로 들어온다)
psql_ -c 'REVOKE CONNECT ON DATABASE postgres FROM PUBLIC' -c 'REVOKE CONNECT ON DATABASE template1 FROM PUBLIC'
