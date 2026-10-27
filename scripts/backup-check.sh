#!/usr/bin/env bash
# 백업 설정 점검(읽기 전용, Docker 불필요). doctor.sh --up 과 init 이 부른다. 사용: backup-check.sh
# 종료 코드 0 통과, 2 CRIT(설정 없음·불완전, 개인키가 서버에 있음). 같은 검증 규칙은 backup-lib.sh 의 backup_load_config 가 정본이다.
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/backup-lib.sh"
BACKUP_CHECK_ONLY=1
backup_load_config   # 문제가 있으면 CRIT 를 내고 종료 코드 2 로 끝낸다
if [ "${BACKUP_ALLOW_PLAINTEXT:-0}" = 1 ]; then echo "CRIT: BACKUP_ALLOW_PLAINTEXT=1 은 시험 전용이다. 운영에서는 암호화한다" >&2; exit 2; fi
[ -d "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 가 없다: $BACKUP_DIR (마운트·생성 후 다시)" >&2; exit 2; }
[ -w "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 에 쓸 수 없다: $BACKUP_DIR" >&2; exit 2; }
fstype=$(stat -f -c %T "$BACKUP_DIR" 2>/dev/null || echo ?)
if [ "$(stat -c %d "$BACKUP_DIR")" = "$(stat -c %d "$DEPLOY_ROOT")" ]; then
  echo "WARN: BACKUP_DIR($BACKUP_DIR)가 이 리포지토리와 같은 디스크($fstype)다. 서버 디스크가 죽으면 백업도 같이 사라진다: 다른 디스크나 원격 마운트를 쓴다"
else echo "OK: BACKUP_DIR 가 이 리포지토리와 다른 장치($fstype)에 있다 (서버 밖인지는 이 점검이 알 수 없다)"; fi
echo "OK: 백업 설정 (보관 ${BACKUP_RETENTION_DAYS}일, 암호화 $BACKUP_CRYPT, 수신자 공개키 파일 $BACKUP_ENCRYPT_RECIPIENTS)"
