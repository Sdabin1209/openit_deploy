#!/usr/bin/env bash
# 백업 설정 점검(읽기 전용, Docker 불필요). doctor.sh --up 과 init 이 부른다. 사용: backup-check.sh
# 종료 코드 0 통과, 2 CRIT(설정 없음·불완전, 암호 파일 없음·모드 틀림·저장소 안에 있음, 옛 키). 같은 검증 규칙은 backup-lib.sh 의 backup_load_config 가 정본이다.
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/backup-lib.sh"
BACKUP_CHECK_ONLY=1
backup_load_config   # 문제가 있으면 CRIT 를 내고 종료 코드 2 로 끝낸다
# 백업 보관 기간은 운영 데이터 보존 기간 중 가장 짧은 값 이하여야 한다(U30, ADR 0044): 지운 데이터가 백업에 더 오래 남으면 보존 정책이 우회된다
"$DEPLOY_PY" "$DEPLOY_ROOT/scripts/retention_check.py" --backup-days "$BACKUP_RETENTION_DAYS" || { echo "CRIT: 백업 보관 기간이 운영 데이터 보존 기간보다 길다(위 메시지)" >&2; exit 2; }
if [ "$BACKUP_MODE" = rest ]; then
  echo "OK: 서버 밖 append-only 저장소 ${BACKUP_REPOSITORY} (restic rest-server, 서버는 쓰기만 하고 지우거나 고칠 수 없다: 이 점검은 서버 쪽 설정이 append-only 인지 알 수 없다 -> 저장소 쪽에서 확인한다, runbook 4-7)"
  echo "OK: 백업 설정 (보관 ${BACKUP_RETENTION_DAYS}일은 저장소 쪽 backup-prune.sh 가 적용, 암호 파일 $BACKUP_PASSWORD_FILE)"; exit 0
fi
echo "WARN: BACKUP_DIR(로컬 폴더) 모드다. 서버가 백업을 지우거나 고칠 수 있어 침해 시 백업도 같이 잃는다(D112). 운영은 BACKUP_REPOSITORY(서버 밖 append-only rest-server)를 쓴다"
[ -d "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 가 없다: $BACKUP_DIR (마운트·생성 후 다시)" >&2; exit 2; }
[ -w "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 에 쓸 수 없다: $BACKUP_DIR" >&2; exit 2; }
fstype=$(stat -f -c %T "$BACKUP_DIR" 2>/dev/null || echo ?)
if [ "$(stat -c %d "$BACKUP_DIR")" = "$(stat -c %d "$DEPLOY_ROOT")" ]; then
  echo "WARN: BACKUP_DIR($BACKUP_DIR)가 이 리포지토리와 같은 디스크($fstype)다. 서버 디스크가 죽으면 백업도 같이 사라진다: 다른 디스크나 원격 마운트를 쓴다"
else echo "OK: BACKUP_DIR 가 이 리포지토리와 다른 장치($fstype)에 있다 (서버 밖인지는 이 점검이 알 수 없다)"; fi
echo "OK: 백업 설정 (보관 ${BACKUP_RETENTION_DAYS}일, restic 저장소 $BACKUP_DIR/restic, 암호 파일 $BACKUP_PASSWORD_FILE)"
