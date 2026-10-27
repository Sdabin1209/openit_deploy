#!/usr/bin/env bash
# PostgreSQL 복구. 사용: pg-restore.sh <데이터베이스> <스냅샷 디렉터리> --yes
# 그 데이터베이스를 쓰는 서비스가 멈춰 있어야 한다(다른 접속이 있으면 거부). 해시를 검증한 뒤 데이터베이스의 객체를 지우고(--clean) 한 트랜잭션으로 되살린다.
# 서버·데이터베이스·계정은 이미 있어야 한다(새 볼륨이면 postgres 서비스를 먼저 띄우면 초기화 스크립트가 만든다). 환경: DEPLOY_PROJECT(기본 deploy)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
DB=${1:?데이터베이스}; SNAP=${2:?스냅샷}; [ "${3:-}" = "--yes" ] || die "--yes 가 필요하다(데이터베이스의 현재 내용을 지운다)"
[[ "$DB" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $DB"
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
F="$SNAP/$DB.dump"
if [ ! -f "$F" ]; then   # 암호화된 스냅샷: 복호 개인키는 서버에 없다. 사람이 키로 풀어 같은 폴더에 $DB.dump 를 둔 뒤 다시 실행한다(풀고 나면 평문이니 끝나면 지운다)
  for e in age gpg; do [ -f "$F.$e" ] && die "스냅샷이 암호화되어 있다: $F.$e 를 개인키로 복호해 $F 로 둔다 (age -d -i <키> -o $F $F.$e  /  gpg -d -o $F $F.$e). docs/runbook.md 4절"; done
fi
[ -f "$F" ] && [ -f "$SNAP/MANIFEST.json" ] || die "스냅샷에 $DB.dump 또는 MANIFEST.json 이 없다: $SNAP"
WANT=$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]+"/MANIFEST.json"))["files"][sys.argv[2]+".dump"]["sha256"])' "$SNAP" "$DB")
[ "sha256:$(sha256sum "$F" | cut -d' ' -f1)" = "$WANT" ] || { echo "해시 불일치: $F" >&2; exit 3; }
OTHERS=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$DB' AND pid <> pg_backend_pid()" | tr -d '\r')
[ "$OTHERS" = 0 ] || die "$DB 에 다른 접속이 $OTHERS 개 있다. 이 데이터베이스를 쓰는 서비스를 먼저 멈춘다"
# 암호화된 백업은 BACKUP_DECRYPT_CMD(비밀키를 가진 쪽이 준다, 서버에는 키가 없다)로 풀어 pg_restore 에 넘긴다
if [ $ENCRYPTED = 1 ]; then backup_decrypt < "$F" | "$DOCKER" exec -i "$C" pg_restore -U "$DB" -d "$DB" --clean --if-exists --no-owner --single-transaction --exit-on-error
else "$DOCKER" exec -i "$C" pg_restore -U "$DB" -d "$DB" --clean --if-exists --no-owner --single-transaction --exit-on-error < "$F"; fi
echo "복구: $DB <- $SNAP"
