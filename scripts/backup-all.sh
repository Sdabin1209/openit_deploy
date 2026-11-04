#!/usr/bin/env bash
# deploy 자신의 데이터 백업 잡 하나: 이미지 레지스트리 볼륨(backup.sh registry-data)과 secrets/(backup-secrets.sh)를 config/backup.env 로 백업한다. 영역 데이터는 영역의 백업 잡이 한다(계약 3.4.16). 설정이 없거나 불완전하면 두 스크립트가 "CRIT:" 와 종료 코드 2 로 실패한다(D88 U6, 백업 없이 운영하지 않는다).
# jobs.yaml 의 backup 잡이 부른다. 둘 중 하나라도 실패하면 실패(종료 코드는 먼저 실패한 것). 사용: backup-all.sh   환경: DEPLOY_PROJECT, BACKUP_CONFIG
set -uo pipefail
D="$(dirname "$0")"; rc=0
bash "$D/backup.sh" || rc=$?
bash "$D/backup-secrets.sh" || { r=$?; [ $rc != 0 ] || rc=$r; }   # secrets/ 는 별도 산출물(암호화, 비식별 salt 연속성)
exit $rc
