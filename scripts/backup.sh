#!/usr/bin/env bash
# 저장소(볼륨)별 백업. 사용: backup.sh [저장소 ...]   저장소: gate-data models-data (파일 저장소. 비우면 gate-data). 데이터베이스는 PostgreSQL 이라 pg-backup.sh
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env)
# 저장소 기본: BACKUP_FILE_STORES(backup.env, 기본 gate-data models-data). registry-data(로컬 레지스트리 볼륨)도 이름을 주면 된다. 파일은 600, 폴더 700.
# 설정(BACKUP_DIR, BACKUP_RETENTION_DAYS)이 없거나 비어 있으면 거부한다(코드에 기본값 없음, O16 미정).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
[ -f "$CFG" ] || { echo "거부: 백업 설정 파일이 없다: $CFG (config/backup.env.example 참고. 주기·보관 기간은 사용자 결정 O16)" >&2; exit 2; }
BACKUP_DIR=; BACKUP_RETENTION_DAYS=
set -a; source "$CFG"; set +a
[ -n "$BACKUP_DIR" ] || { echo "거부: BACKUP_DIR 이 비어 있다" >&2; exit 2; }
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "거부: BACKUP_RETENTION_DAYS 가 비었거나 정수가 아니다: '$BACKUP_RETENTION_DAYS'" >&2; exit 2; }
P=${DEPLOY_PROJECT:-deploy}
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
[ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금 파일에 없다"
umask 077; mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true
STORES=${*:-${BACKUP_FILE_STORES:-gate-data models-data}}   # 세션·문항·로그·레지스트리는 PostgreSQL(D85)이라 pg-backup.sh 가 맡는다. 남은 파일 저장소는 번들(gate-data/releases)
TS=$(date -u +%Y%m%dT%H%M%SZ)
for s in $STORES; do
  mkdir -p "$BACKUP_DIR/$s"
  # 일관성은 SQLite backup API(읽기 전용 연결)가 보장한다. WAL 모드 DB를 읽으려면 -shm 파일이 필요해 볼륨을 쓰기 가능으로 붙이고,
  # 도구는 원본을 바꾸지 않는다(만든 -wal/-shm 은 지운다). 서비스가 떠 있어도 된다.
  vol="${P}_${s}"; [ "$s" != registry-data ] || vol="${REGISTRY_PROJECT:-deploy-registry}_registry-data"   # 로컬 레지스트리 볼륨은 별도 프로젝트
  "$DOCKER" volume inspect "$vol" >/dev/null 2>&1 || { echo "건너뜀: 볼륨 $vol 이 없다" >&2; continue; }
  "$DOCKER" run --rm -v "${vol}:/src" -v "$BACKUP_DIR:/out" -v "$DEPLOY_ROOT/scripts:/tool:ro" \
    "$UTIL" python /tool/backup_tool.py backup /src "/out/$s/.partial-$TS" --store "$s" --owner "$(id -u):$(id -g)" >/dev/null
  chmod -R go-rwx "$BACKUP_DIR/$s/.partial-$TS"
  mv "$BACKUP_DIR/$s/.partial-$TS" "$BACKUP_DIR/$s/$TS"
  echo "백업: $s -> $BACKUP_DIR/$s/$TS"
  # 보관 기간이 지난 스냅샷을 지운다. 방금 만든 것과 가장 최근 하나는 남긴다.
  if [ "$BACKUP_RETENTION_DAYS" -ge 0 ]; then
    mapfile -t old < <(find "$BACKUP_DIR/$s" -mindepth 1 -maxdepth 1 -type d -name '2*' -mtime +"$BACKUP_RETENTION_DAYS" | sort)
    total=$(find "$BACKUP_DIR/$s" -mindepth 1 -maxdepth 1 -type d -name '2*' | wc -l)
    for d in "${old[@]}"; do [ "$total" -gt 1 ] || break; rm -rf "$d"; total=$((total-1)); echo "보관 기간 경과로 삭제: $d"; done
  fi
done
