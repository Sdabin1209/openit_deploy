#!/usr/bin/env bash
# 저장소(볼륨)별 백업. 사용: backup.sh [저장소 ...]   저장소: gate-data models-data datasets-data registry-data gateway-data (파일 저장소. 비우면 전부). 데이터베이스는 PostgreSQL 이라 pg-backup.sh 가 맡는다.
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env), REGISTRY_PROJECT(기본 deploy-registry: 레지스트리 볼륨은 별도 프로젝트 소유)
# 설정(BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_PASSWORD_FILE)이 없거나 비어 있으면 CRIT 로 거부한다(종료 코드 2, 코드에 기본값 없음). 설정·restic 호출은 backup-lib.sh.
# 저장소 하나가 restic 스냅샷 하나다(--host 가 저장소 이름, 태그 set-<UTC 시각>). restic 이 중복 제거·암호화(AES-256, 인증)·무결성 해시를 맡는다(ADR 0038).
# gateway-data(내부 CA 루트·비밀키)도 같은 경로로 백업한다(점검 M3). 복원하면 루트가 유지되어 기기들이 다시 신뢰하지 않아도 된다(runbook 9-1).
# datasets-data 를 넣은 이유: 학습 데이터셋은 게시된 버전이 불변이고 모델 패키지 계보(lineage.dataset)가 id·버전·content_hash 로 가리킨다. 잃으면 같은 데이터로 재학습·재현을 못 한다.
# registry-data 를 넣은 이유: 이미지는 CI 로 다시 만들 수 있으나 digest 로 고정된 운영 이미지를 레지스트리가 잃으면 롤백이 불가능하다(docs/adr/0020-backup-tool-and-encryption.md).
# 제외: datasets-data/.tmp 는 dataset-store 서버의 요청 임시 폴더다(시작 때 비우고 다시 만든다, synthetic-data ADR 0012). 복구할 데이터가 아니다.
# SQLite backup API 는 쓰지 않는다: 운영 저장소는 PostgreSQL(D85)이고 이 볼륨들에는 SQLite 가 없다(ADR 0038). 서비스가 떠 있어도 되는 저장소는 불변 파일 위주다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
P=${DEPLOY_PROJECT:-deploy}
STORES=${*:-gate-data models-data datasets-data registry-data gateway-data}
for s in $STORES; do [[ "$s" =~ ^[a-z][a-z0-9-]*$ ]] || die "저장소 이름 형식 오류: $s"; done
TS=$(date -u +%Y%m%dT%H%M%SZ)
# 겹침 실행 방지(점검 M4): 같은 BACKUP_DIR 에서 두 번째 백업이 동시에 돌면 forget --prune 이 진행 중인 백업과 겹친다. 잠금을 못 잡으면 거부한다(종료 4)
exec 9>"$BACKUP_LOCK_FILE"; flock -n 9 || { echo "CRIT: 다른 백업이 같은 저장소로 진행 중이다($BACKUP_LOCK_FILE): 겹쳐 돌리지 않는다" >&2; exit 4; }
backup_ensure_repo
vol_of() { case "$1" in registry-data) echo "${REGISTRY_PROJECT:-deploy-registry}_registry-data";; *) echo "${P}_$1";; esac; }
for s in $STORES; do
  V=$(vol_of "$s")
  "$DOCKER" volume inspect "$V" >/dev/null 2>&1 || { case "$s" in registry-data) echo "건너뜀: 레지스트리 볼륨 $V 가 없다(레지스트리 프로젝트가 이 서버에 없음)"; continue;; *) die "볼륨이 없다: $V";; esac; }
  ex=(); [ "$s" != datasets-data ] || ex=(--exclude /data/.tmp)
  # 볼륨은 읽기 전용으로 붙인다. 서비스가 쓰는 중이어도 파일마다 일관된 사본이다(restic 은 읽는 도중 바뀐 파일을 경고로 알린다)
  out=$(backup_restic "${BACKUP_ROOT_ARGS[@]}" -v "$V:/data:ro" -- backup /data --host "$s" --tag "set-$TS" "${ex[@]+"${ex[@]}"}" --json) || { rc=$?; backup_fixperm; die "restic backup 실패: $s (종료 $rc)"; }
  backup_fixperm
  sid=$(sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' <<<"$out" | tail -1); [ -n "$sid" ] || die "스냅샷 ID 를 읽지 못했다: $s"
  echo "백업: $s -> restic 스냅샷 $sid (restic, 암호화)"
done
backup_forget
