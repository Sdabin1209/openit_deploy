#!/usr/bin/env bash
# PostgreSQL 백업(pg_dump 사용자 정의 형식을 restic 에 표준 입력으로 바로 넣는다). 사용: pg-backup.sh [데이터베이스 ...]   (비우면 survey qa ops_log ops_failure gate)
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env) -- 설정 검증·restic 호출은 backup-lib.sh (BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_PASSWORD_FILE)
# 서버가 떠 있어도 된다. 데이터베이스의 소유 계정으로 컨테이너 안 소켓에 접속해 덤프한다(최소 권한, 암호 불필요).
# 같은 시점 한계(왜 이렇게): PostgreSQL 은 데이터베이스 사이에 하나의 스냅샷을 공유할 수 없다(pg_dump --snapshot 도 한 데이터베이스 안에서만 유효).
#   그래서 (1) 각 덤프는 자기 데이터베이스에서는 단일 트랜잭션 스냅샷이고 (2) 5개를 병렬로 동시에 시작해 시간차를 덤프 하나가 걸리는 시간 이하로 줄이며
#   (3) 같은 실행의 스냅샷에 같은 태그 set-<UTC 시각> 을 붙이고 스냅샷마다 restic 이 시각을 남긴다. 데이터베이스 사이의 참조는 HTTP·ID 로 느슨하게 이어져 있어 시간차 동안
#   한쪽에만 있는 행은 생길 수 있다(예: survey 세션의 결과가 ops_log 에 아직 없음). 정확히 같은 시점이 필요하면 쓰기 서비스를 멈추고 돌린다(docs/runbook.md 4절).
# 결과: restic 스냅샷 하나가 데이터베이스 하나(--host pg-<db>, 파일 <db>.dump, 태그 set-<시각>·pg-<서버 버전>). 평문 덤프는 디스크에 쓰이지 않는다(파이프로 암호화 저장소에 바로 간다).
# 덤프가 중간에 실패하면(pg_dump 가 비정상 종료) 파이프로 이미 들어간 불완전한 스냅샷을 forget 해서 성공한 백업처럼 남지 않게 한다.
# 볼륨(pg-data)을 파일째 복사하는 방식은 쓰지 않는다: 서버가 쓰는 중에는 일관되지 않다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
P=${DEPLOY_PROJECT:-deploy}
C=$(pg_container "$P"); [ -n "$C" ] || die "프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다"
DBS=${*:-$PG_DBS}
TS=$(date -u +%Y%m%dT%H%M%SZ)
VER=$("$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc 'SHOW server_version' | tr -d '\r' | tr -d ' ,')
for db in $DBS; do [[ "$db" =~ ^[a-z][a-z0-9_]*$ ]] || die "데이터베이스 이름이 규칙에 맞지 않는다: $db"; done
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true
exec 9>"$BACKUP_DIR/.backup.lock"; flock -n 9 || { echo "CRIT: 다른 백업이 같은 BACKUP_DIR 에서 진행 중이다($BACKUP_DIR/.backup.lock): 겹쳐 돌리지 않는다" >&2; exit 4; }
backup_ensure_repo
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
SET_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
dump_one() { # 병렬로 도는 한 데이터베이스: pg_dump -> restic --stdin. 결과 코드와 restic 요약(JSON)을 파일로 남긴다
  local db=$1
  if "$DOCKER" exec "$C" pg_dump -Fc -U "$db" -d "$db" 2>"$W/$db.err" | backup_restic -i -- backup --stdin --stdin-filename "$db.dump" --host "pg-$db" --tag "set-$TS" --tag "pg-$VER" --json >"$W/$db.json" 2>>"$W/$db.err"; then echo 0 > "$W/$db.rc"; else echo 1 > "$W/$db.rc"; fi
}
pids=(); for db in $DBS; do dump_one "$db" & pids+=($!); done
for p in "${pids[@]}"; do wait "$p" || true; done
fail=0
for db in $DBS; do
  # 성공 조건: 파이프 전체 성공 + 스냅샷 ID 가 있고 처리한 바이트가 0 보다 크다(빈 덤프는 실패)
  sid=$(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' "$W/$db.json" 2>/dev/null | tail -1)
  bytes=$(sed -n 's/.*"total_bytes_processed":\([0-9]*\).*/\1/p' "$W/$db.json" 2>/dev/null | tail -1)
  if [ "$(cat "$W/$db.rc" 2>/dev/null)" = 0 ] && [ -n "$sid" ] && [ "${bytes:-0}" -gt 0 ]; then continue; fi
  fail=1; echo "실패: pg-$db ($(tail -1 "$W/$db.err" 2>/dev/null | cut -c1-160))" >&2
done
if [ $fail = 1 ]; then   # 부분 결과는 남기지 않는다: 이 실행이 만든 스냅샷(요약 JSON 의 ID)을 모두 지운다(불완전한 것 포함, 다른 실행의 스냅샷은 건드리지 않는다)
  ids=$(for db in $DBS; do sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' "$W/$db.json" 2>/dev/null; done | sort -u)
  # shellcheck disable=SC2086
  [ -z "$ids" ] || backup_restic -- forget $ids --quiet >/dev/null 2>&1 || echo "경고: 불완전한 스냅샷을 지우지 못했다: $ids" >&2
fi
[ $fail = 0 ] || die "pg_dump 실패 또는 빈 덤프(데이터베이스 중 하나 이상). 이 실행의 스냅샷은 모두 버렸다"
SET_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
for db in $DBS; do echo "백업: pg-$db -> restic 스냅샷 $(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' "$W/$db.json" | tail -1) (restic, 암호화)"; done
backup_forget
echo "백업 세트: set-$TS 데이터베이스 $(echo $DBS | wc -w)개, 덤프 시작 $SET_START ~ 끝 $SET_END (데이터베이스 사이 같은 시점 아님: 스크립트 머리말 참고)"
