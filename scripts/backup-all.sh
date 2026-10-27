#!/usr/bin/env bash
# 백업 잡 하나: 파일 저장소(backup.sh: gate-data 의 번들 등)와 PostgreSQL(pg-backup.sh)을 같은 설정(config/backup.env)으로 백업한다.
# jobs.yaml 의 backup 잡이 부른다. 둘 중 하나라도 실패하면 실패(종료 코드는 먼저 실패한 것). 사용: backup-all.sh   환경: DEPLOY_PROJECT, BACKUP_CONFIG
set -uo pipefail
D="$(dirname "$0")"; rc=0
bash "$D/backup.sh" || rc=$?
bash "$D/pg-backup.sh" || { r=$?; [ $rc != 0 ] || rc=$r; }
exit $rc
