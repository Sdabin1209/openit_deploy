#!/usr/bin/env bash
# PostgreSQL 백업(pg_dump 사용자 정의 형식). 사용: pg-backup.sh [데이터베이스 ...]   (비우면 survey qa ops_log ops_failure gate)
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env) -- backup.sh 와 같은 설정·거부 규칙(BACKUP_DIR, BACKUP_RETENTION_DAYS)
# 서버가 떠 있어도 된다(pg_dump 는 한 시점의 일관된 스냅샷을 읽는다). 데이터베이스의 소유 계정으로 컨테이너 안 소켓에 접속해 덤프한다(최소 권한, 암호 불필요).
# 결과: $BACKUP_DIR/pg-<db>/<UTC 시각>/<db>.dump + MANIFEST.json(해시·크기·서버 버전). 덤프에는 개인정보가 들 수 있어 폴더 700, 파일 600.
# 볼륨(pg-data)을 파일째 복사하는 방식은 쓰지 않는다: 서버가 쓰는 중에는 일관되지 않다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
[ -f "$CFG" ] || { echo "거부: 백업 설정 파일이 없다: $CFG (config/backup.env.example 참고. 주기·보관 기간은 사용자 결정 O16)" >&2; exit 2; }
BACKUP_DIR=; BACKUP_RETENTION_DAYS=
set -a; source "$CFG"; set +a
[ -n "$BACKUP_DIR" ] || { echo "거부: BACKUP_DIR 이 비어 있다" >&2; exit 2; }
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "거부: BACKUP_RETENTION_DAYS 가 비었거나 정수가 아니다: '$BACKUP_RETENTION_DAYS'" >&2; exit 2; }
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
DBS=${*:-$PG_DBS}
TS=$(date -u +%Y%m%dT%H%M%SZ)
umask 077; mkdir -p "$BACKUP_DIR"
VER=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc 'SHOW server_version' | tr -d '\r')
for db in $DBS; do
  [[ "$db" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $db"
  out="$BACKUP_DIR/pg-$db/.partial-$TS"; mkdir -p "$out"
  "$DOCKER" exec "$C" pg_dump -Fc -U "$db" -d "$db" > "$out/$db.dump" || { rm -rf "$out"; die "pg_dump 실패: $db"; }
  [ -s "$out/$db.dump" ] || { rm -rf "$out"; die "빈 덤프: $db"; }
  H=$(sha256sum "$out/$db.dump" | cut -d' ' -f1); SZ=$(stat -c %s "$out/$db.dump")
  printf '{"store": "pg-%s", "database": "%s", "format": "pg_dump -Fc", "server_version": "%s", "created_at": "%s", "files": {"%s.dump": {"sha256": "sha256:%s", "size": %s}}}\n' \
    "$db" "$db" "$VER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$db" "$H" "$SZ" > "$out/MANIFEST.json"
  mv "$out" "$BACKUP_DIR/pg-$db/$TS"
  echo "백업: pg-$db -> $BACKUP_DIR/pg-$db/$TS"
  if [ "$BACKUP_RETENTION_DAYS" -ge 0 ]; then   # backup.sh 와 같은 규칙: 방금 만든 것과 가장 최근 하나는 남긴다
    mapfile -t old < <(find "$BACKUP_DIR/pg-$db" -mindepth 1 -maxdepth 1 -type d -name '2*' -mtime +"$BACKUP_RETENTION_DAYS" | sort)
    total=$(find "$BACKUP_DIR/pg-$db" -mindepth 1 -maxdepth 1 -type d -name '2*' | wc -l)
    for d in "${old[@]}"; do [ "$total" -gt 1 ] || break; rm -rf "$d"; total=$((total-1)); echo "보관 기간 경과로 삭제: $d"; done
  fi
done
