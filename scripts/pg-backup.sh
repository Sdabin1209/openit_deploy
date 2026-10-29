#!/usr/bin/env bash
# PostgreSQL 백업(pg_dump 사용자 정의 형식을 restic 에 표준 입력으로 바로 넣는다). 사용: pg-backup.sh [데이터베이스 ...]   (비우면 survey qa ops_log ops_failure gate)
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env) -- 설정 검증·restic 호출은 backup-lib.sh (BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_PASSWORD_FILE)
# 서버가 떠 있어도 된다. 데이터베이스의 소유 계정으로 컨테이너 안 소켓에 접속해 덤프한다(최소 권한, 암호 불필요).
# 같은 시점 한계(왜 이렇게): PostgreSQL 은 데이터베이스 사이에 하나의 스냅샷을 공유할 수 없다(pg_dump --snapshot 도 한 데이터베이스 안에서만 유효).
#   그래서 (1) 각 덤프는 자기 데이터베이스에서는 단일 트랜잭션 스냅샷이고 (2) 5개를 병렬로 동시에 시작해 시간차를 덤프 하나가 걸리는 시간 이하로 줄이며
#   (3) 같은 실행의 스냅샷에 같은 태그 set-<UTC 시각> 을 붙이고 스냅샷마다 restic 이 시각을 남긴다. 데이터베이스 사이의 참조는 HTTP·ID 로 느슨하게 이어져 있어 시간차 동안
#   한쪽에만 있는 행은 생길 수 있다(예: survey 세션의 결과가 ops_log 에 아직 없음). 정확히 같은 시점이 필요하면 쓰기 서비스를 멈추고 돌린다(docs/runbook.md 4절).
# 결과: restic 스냅샷 하나가 데이터베이스 하나(--host pg-<db>, 파일 <db>.dump, 태그 set-<시각>·pg-<서버 버전>). 평문 덤프는 디스크에 쓰이지 않는다(파이프로 암호화 저장소에 바로 간다).
# 덤프가 중간에 실패하면(pg_dump 가 비정상 종료) restic 이 입력 끝을 보기 전에 컨테이너를 죽여 그 데이터베이스의 스냅샷이 만들어지지 않게 한다(append-only 저장소에서는 만든 뒤 지울 수 없다).
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
exec 9>"$BACKUP_LOCK_FILE"; flock -n 9 || { echo "CRIT: 다른 백업이 같은 저장소로 진행 중이다($BACKUP_LOCK_FILE): 겹쳐 돌리지 않는다" >&2; exit 4; }
backup_ensure_repo
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
SET_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
dump_one() { # 병렬로 도는 한 데이터베이스: pg_dump -> restic --stdin. 결과 코드와 restic 요약(JSON)을 파일로 남긴다
  # 왜 이렇게: 서버 밖 append-only 저장소에서는 서버가 스냅샷을 지울 수 없으므로(D112), 불완전한 덤프의 스냅샷은 **만들어지면 안 된다**. restic 은 입력 끝(EOF)을 보면 스냅샷을 만든다.
  # 그래서 pg_dump 의 종료 코드를 알 때까지 파이프를 열어 두고(서브셸이 stdout 을 쥔다), 실패면 EOF 를 주기 전에 restic 컨테이너를 죽인다(업로드된 조각은 스냅샷이 없는 미사용 데이터로 남고 저장소 쪽 prune 이 치운다).
  local db=$1 name="pgbk-$db-$$"
  {
    local rc=0; "$DOCKER" exec "$C" pg_dump -Fc -U "$db" -d "$db" 2>"$W/$db.err" || rc=$?   # set -e 로 서브셸이 여기서 끝나면 아래 kill 이 실행되지 않아 EOF 가 가고 빈 스냅샷이 만들어진다
    echo $rc > "$W/$db.dumprc"
    if [ $rc != 0 ]; then   # restic 컨테이너가 아직 뜨는 중일 수 있어 죽일 수 있을 때까지 다시 시도한다(그동안 파이프는 열려 있어 EOF 가 가지 않는다)
      for _ in $(seq 1 40); do "$DOCKER" kill "$name" >/dev/null 2>&1 && break; sleep 0.25; done
    fi
  } | backup_restic -i --name "$name" -- backup --stdin --stdin-filename "$db.dump" --host "pg-$db" --tag "set-$TS" --tag "pg-$VER" --json >"$W/$db.json" 2>>"$W/$db.err"
  local prc=${PIPESTATUS[1]}
  if [ "$(cat "$W/$db.dumprc" 2>/dev/null)" = 0 ] && [ "$prc" = 0 ]; then echo 0 > "$W/$db.rc"; else echo 1 > "$W/$db.rc"; fi
}
pids=(); for db in $DBS; do dump_one "$db" & pids+=($!); done
for p in "${pids[@]}"; do wait "$p" || true; done
fail=0
for db in $DBS; do
  # 성공 조건: 덤프와 restic 모두 성공 + 스냅샷 ID 가 있고 처리한 바이트가 0 보다 크다(빈 덤프는 실패)
  sid=$(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' "$W/$db.json" 2>/dev/null | tail -1)
  bytes=$(sed -n 's/.*"total_bytes_processed":\([0-9]*\).*/\1/p' "$W/$db.json" 2>/dev/null | tail -1)
  if [ "$(cat "$W/$db.rc" 2>/dev/null)" = 0 ] && [ -n "$sid" ] && [ "${bytes:-0}" -gt 0 ]; then continue; fi
  fail=1; echo "실패: pg-$db ($(tail -1 "$W/$db.err" 2>/dev/null | cut -c1-160))" >&2
done
# 부분 결과: 성공한 데이터베이스의 스냅샷은 남는다(append-only 라 지울 수 없다). 같은 set 태그에 5개가 모두 있는 세트만 완성본이다(runbook 4-3)
[ $fail = 0 ] || die "pg_dump 또는 저장 실패(데이터베이스 중 하나 이상). 실패한 데이터베이스의 스냅샷은 만들어지지 않았다. 이 실행(set-$TS)은 불완전한 세트다"
SET_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
for db in $DBS; do echo "백업: pg-$db -> restic 스냅샷 $(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' "$W/$db.json" | tail -1) (restic, 암호화)"; done
backup_forget
echo "백업 세트: set-$TS 데이터베이스 $(echo $DBS | wc -w)개, 덤프 시작 $SET_START ~ 끝 $SET_END (데이터베이스 사이 같은 시점 아님: 스크립트 머리말 참고)"
