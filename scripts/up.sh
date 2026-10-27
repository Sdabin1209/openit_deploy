#!/usr/bin/env bash
# 사용: up.sh <프로젝트> [--external-inference <URL>] [compose up 인자...]   기본 프로젝트는 deploy. 시험은 COMPOSE_EXTRA=compose.test.yaml 로 덮어쓴다.
#   --external-inference <URL>   이 구성의 model-serving 을 끄고 그 주소의 추론 서버를 쓴다(compose.external-inference.yaml, D72).
#                                토큰은 환경 변수 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE(경로)로 준다. 값을 인자로 받지 않는다.
set -euo pipefail
if [ "${1:-}" = -h ] || [ "${1:-}" = --help ]; then sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0; fi
# 서버 기동용 사전 점검(docker·compose·데몬·자격증명). 건너뛰기: DEPLOY_SKIP_DOCTOR=1
source "$(dirname "$0")/lib.sh"
P=deploy; case "${1:-}" in ""|-*) ;; *) P=$1; shift;; esac
# 운영 프로젝트(deploy)는 백업 설정이 없으면 기동하지 않는다(D88 U6). 시험 프로젝트(deploy-e2e-* 등)는 건너뛴다.
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" --up $([ "$P" = deploy ] && echo --backup) || exit 1
ARGS=(); EXT=""
while [ $# -gt 0 ]; do case "$1" in
  --external-inference) [ $# -ge 2 ] || die "--external-inference 에는 URL이 필요하다"; EXT=$2; shift 2;;
  --external-inference=*) EXT=${1#*=}; shift;;
  *) ARGS+=("$1"); shift;; esac; done
if [ -n "$EXT" ]; then
  external_inference_setup "$EXT"
  [ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --inference "$EXT" || exit 1
fi
set -- "${ARGS[@]+"${ARGS[@]}"}"
bash "$DEPLOY_ROOT/scripts/check-compose.sh" >/dev/null
dc "$P" up -d --wait "$@"
