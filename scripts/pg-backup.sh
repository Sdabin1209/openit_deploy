#!/usr/bin/env bash
# PostgreSQL 백업(pg_dump 사용자 정의 형식). 사용: pg-backup.sh [데이터베이스 ...]   (비우면 survey qa ops_log ops_failure gate)
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env) -- 설정 검증·암호화는 backup-lib.sh (BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_ENCRYPT_RECIPIENTS)
# 서버가 떠 있어도 된다. 데이터베이스의 소유 계정으로 컨테이너 안 소켓에 접속해 덤프한다(최소 권한, 암호 불필요).
# 같은 시점 한계(왜 이렇게): PostgreSQL 은 데이터베이스 사이에 하나의 스냅샷을 공유할 수 없다(pg_dump --snapshot 도 한 데이터베이스 안에서만 유효).
#   그래서 (1) 각 덤프는 자기 데이터베이스에서는 단일 트랜잭션 스냅샷이고 (2) 5개를 병렬로 동시에 시작해 시간차를 덤프 하나가 걸리는 시간 이하로 줄이며
#   (3) 시작·끝 시각을 BACKUP_SET.json 에 남긴다. 데이터베이스 사이의 참조는 HTTP·ID 로 느슨하게 이어져 있어 시간차 동안 한쪽에만 있는 행은
#   생길 수 있다(예: survey 세션의 결과가 ops_log 에 아직 없음). 정확히 같은 시점이 필요하면 쓰기 서비스를 멈추고 돌린다(docs/runbook.md 4절).
# 결과: $BACKUP_DIR/pg-<db>/<UTC 시각>/<db>.dump[.age|.gpg] + MANIFEST.json(평문 해시·크기·서버 버전·암호화 여부). 폴더 700, 파일 600.
#   암호화하면 평문은 디스크에 남기지 않는다(암호화 성공 뒤 삭제). 복호 개인키는 서버에 없다: 복원은 사람이 키로 풀어 pg-restore.sh 에 준다.
# 볼륨(pg-data)을 파일째 복사하는 방식은 쓰지 않는다: 서버가 쓰는 중에는 일관되지 않다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
DBS=${*:-$PG_DBS}
TS=$(date -u +%Y%m%dT%H%M%SZ)
VER=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc 'SHOW server_version' | tr -d '\r')
for db in $DBS; do [[ "$db" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $db"; done
W=$(mktemp -d "$BACKUP_DIR/.work-$TS-XXXX"); trap 'rm -rf "$W"' EXIT
SET_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
dump_one() { # 병렬로 도는 한 데이터베이스의 덤프. 시작·끝 시각을 파일로 남긴다
  local db=$1 o="$W/$1"; mkdir -p "$o"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$o/started"
  "$DOCKER" exec "$C" pg_dump -Fc -U "$db" -d "$db" > "$o/$db.dump" && [ -s "$o/$db.dump" ] && date -u +%Y-%m-%dT%H:%M:%SZ > "$o/finished"
}
pids=(); for db in $DBS; do dump_one "$db" & pids+=($!); done
fail=0; for i in "${!pids[@]}"; do wait "${pids[$i]}" || fail=1; done
[ $fail = 0 ] || die "pg_dump 실패 또는 빈 덤프(데이터베이스 중 하나 이상). 부분 결과는 버렸다"
for db in $DBS; do [ -s "$W/$db/finished" ] || [ -f "$W/$db/finished" ] || die "덤프가 끝나지 않았다: $db"; done
SET_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
for db in $DBS; do
  o="$W/$db"; f="$o/$db.dump"
  H=$(sha256sum "$f" | cut -d' ' -f1); SZ=$(stat -c %s "$f")
  enc=$(backup_encrypt "$f" "$f") || die "암호화 실패: $db"
  EH=$(sha256sum "$enc" | cut -d' ' -f1); name=$(basename "$enc")
  printf '{"store": "pg-%s", "database": "%s", "format": "pg_dump -Fc", "server_version": "%s", "created_at": "%s", "dump_started": "%s", "dump_finished": "%s", "encryption": "%s", "files": {"%s.dump": {"sha256": "sha256:%s", "size": %s}}, "stored_file": {"name": "%s", "sha256": "sha256:%s"}}\n' \
    "$db" "$db" "$VER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(cat "$o/started")" "$(cat "$o/finished")" "$BACKUP_CRYPT" "$db" "$H" "$SZ" "$name" "$EH" > "$o/MANIFEST.json"
  rm -f "$o/started" "$o/finished"
  mkdir -p "$BACKUP_DIR/pg-$db"; chmod 700 "$BACKUP_DIR/pg-$db"; chmod 600 "$o"/*; chmod 700 "$o"
  mv "$o" "$BACKUP_DIR/pg-$db/$TS"
  echo "백업: pg-$db -> $BACKUP_DIR/pg-$db/$TS ($BACKUP_CRYPT)"
  backup_prune "$BACKUP_DIR/pg-$db"
done
echo "백업 세트: $TS 데이터베이스 $(echo $DBS | wc -w)개, 덤프 시작 $SET_START ~ 끝 $SET_END (데이터베이스 사이 같은 시점 아님: 스크립트 머리말 참고)"
