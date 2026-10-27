#!/usr/bin/env bash
# PostgreSQL 백업(pg_dump 사용자 정의 형식). 사용: pg-backup.sh [데이터베이스 ...]   (비우면 survey qa ops_log ops_failure gate)
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env) -- backup.sh 와 같은 설정·거부 규칙(BACKUP_DIR, BACKUP_RETENTION_DAYS)
# 서버가 떠 있어도 된다(pg_dump 는 데이터베이스 하나 안에서 한 시점의 일관된 스냅샷을 읽는다. 데이터베이스 사이는 아래 설명). 데이터베이스의 소유 계정으로 컨테이너 안 소켓에 접속해 덤프한다(최소 권한, 암호 불필요).
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
BACKUP_ENCRYPT=none; BACKUP_RECIPIENT_FILE=
set -a; source "$CFG"; set +a
ENC=${BACKUP_ENCRYPT:-none}
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
DBS=${*:-$PG_DBS}
TS=$(date -u +%Y%m%dT%H%M%SZ); SET_ID="set-$TS"; T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
umask 077; mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true
VER=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc 'SHOW server_version' | tr -d '\r')
# 시점 일관성(점검 C7): pg_dump 는 데이터베이스 하나 안에서만 한 시점 스냅샷을 준다. 데이터베이스 사이(survey·qa·ops_log·ops_failure·gate)는 하나의 트랜잭션으로 묶을 수 없다.
# 그래서 모두 동시에 시작해 시간차를 최소로 하고(아래), 같은 backup_set 과 시작·끝 시각을 MANIFEST 에 남긴다. 완전한 일치가 필요하면 쓰는 서비스를 잠시 멈추고 돌린다(docs/runbook.md 4절).
for db in $DBS; do [[ "$db" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $db"; done
EXT=dump; [ "$ENC" = none ] || EXT=dump.enc
dump_one() { # dump_one <db> : 동시에 돌린다. 실패하면 비영 종료 코드
  local db=$1 out="$BACKUP_DIR/pg-$1/.partial-$TS"; mkdir -p "$out"
  { "$DOCKER" exec "$C" pg_dump -Fc -U "$db" -d "$db" | backup_encrypt > "$out/$db.$EXT"; } 2>"$out/err.log" || { cat "$out/err.log" >&2; rm -rf "$out"; return 1; }
  rm -f "$out/err.log"; [ -s "$out/$db.$EXT" ] || { rm -rf "$out"; return 1; }
  chmod 600 "$out/$db.$EXT"; return 0
}
pids=(); for db in $DBS; do dump_one "$db" & pids+=($!); done
fail=0; for i in "${!pids[@]}"; do wait "${pids[$i]}" || fail=1; done
T1=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ $fail = 1 ]; then for db in $DBS; do rm -rf "$BACKUP_DIR/pg-$db/.partial-$TS"; done; die "pg_dump 실패(일부 또는 전부). 만든 사본은 모두 버렸다"; fi
for db in $DBS; do
  out="$BACKUP_DIR/pg-$db/.partial-$TS"
  H=$(sha256sum "$out/$db.$EXT" | cut -d' ' -f1); SZ=$(stat -c %s "$out/$db.$EXT")
  printf '{"store": "pg-%s", "database": "%s", "format": "pg_dump -Fc", "server_version": "%s", "created_at": "%s", "backup_set": "%s", "set_started_at": "%s", "set_finished_at": "%s", "encryption": "%s", "files": {"%s.%s": {"sha256": "sha256:%s", "size": %s}}}\n' \
    "$db" "$db" "$VER" "$T1" "$SET_ID" "$T0" "$T1" "$ENC" "$db" "$EXT" "$H" "$SZ" > "$out/MANIFEST.json"
  chmod 600 "$out/MANIFEST.json"; chmod 700 "$out"
  mv "$out" "$BACKUP_DIR/pg-$db/$TS"
  echo "백업: pg-$db -> $BACKUP_DIR/pg-$db/$TS (암호화: $ENC, 세트 $SET_ID)"
  if [ "$BACKUP_RETENTION_DAYS" -ge 0 ]; then   # backup.sh 와 같은 규칙: 방금 만든 것과 가장 최근 하나는 남긴다
    mapfile -t old < <(find "$BACKUP_DIR/pg-$db" -mindepth 1 -maxdepth 1 -type d -name '2*' -mtime +"$BACKUP_RETENTION_DAYS" | sort)
    total=$(find "$BACKUP_DIR/pg-$db" -mindepth 1 -maxdepth 1 -type d -name '2*' | wc -l)
    for d in "${old[@]}"; do [ "$total" -gt 1 ] || break; rm -rf "$d"; total=$((total-1)); echo "보관 기간 경과로 삭제: $d"; done
  fi
done
