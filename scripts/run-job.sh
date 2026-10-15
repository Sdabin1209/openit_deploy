#!/usr/bin/env bash
# 주기 잡 하나를 한 번 실행한다(컨테이너를 띄우고 끝나면 지운다). 사용: run-job.sh <compose 서비스 이름> [명령 덮어쓰기...]
#  환경: DEPLOY_PROJECT(기본 deploy). 잡 설정 파일이 없으면 거부한다(종료 코드 2).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
svc=${1:?서비스}; shift || true
P=${DEPLOY_PROJECT:-deploy}
if [ "$svc" = job-ops-feedback ] && [ $# -eq 0 ]; then   # 명령을 덮어쓰지 않을 때(진짜 잡 실행)만 설정 파일을 요구한다
  cfg=${OPS_JOB_CONFIG:-$DEPLOY_ROOT/config/ops-feedback-job.yaml}
  [ -f "$cfg" ] || { echo "거부: ops-feedback 잡 설정 파일이 없다: $cfg (CR-D05: 형식은 ops-feedback 문서가 정한다)" >&2; exit 2; }
  export OPS_JOB_CONFIG=$cfg
fi
dc "$P" --profile jobs run --rm --no-deps "$svc" "$@"
