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
[ -f "${JOBS_OVERLAY:-$DEPLOY_ROOT/state/compose.jobs.yaml}" ] || gen_stack_files "$P" || { echo "잡 선언(이미지 라벨 io.openit.jobs)에서 덧씌우기 파일을 못 만들었다" >&2; exit 2; }
# 시간 한도(RUNTIME R9.2·R9.3): 선언의 timeout_seconds(없으면 3600초). 넘기면 잡을 멈추고 이 실행은 실패다(다음 주기에 한 번 다시, R10.12). 한 번에 하나는 systemd oneshot 유닛이 지킨다
secs=$("$DEPLOY_PY" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["services"][sys.argv[2]]["x-openit-timeout-seconds"])' "${JOBS_OVERLAY:-$DEPLOY_ROOT/state/compose.jobs.yaml}" "$svc") || { echo "덧씌우기 파일에 $svc 가 없다" >&2; exit 2; }
timeout --signal=TERM --kill-after=30 "$secs" bash -c 'source "$1/scripts/lib.sh"; shift; dc "$@"' _ "$DEPLOY_ROOT" "$P" --profile jobs run --rm --no-deps "$svc" "$@"
