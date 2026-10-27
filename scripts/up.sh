#!/usr/bin/env bash
# 사용: up.sh <프로젝트> [--external-inference <URL>] [compose up 인자...]   기본 프로젝트는 deploy. 시험은 COMPOSE_EXTRA=compose.test.yaml 로 덮어쓴다.
#   --external-inference <URL>   이 구성의 model-serving 을 끄고 그 주소의 추론 서버를 쓴다(compose.external-inference.yaml, D72).
#                                토큰은 환경 변수 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE(경로)로 준다. 값을 인자로 받지 않는다.
set -euo pipefail
if [ "${1:-}" = -h ] || [ "${1:-}" = --help ]; then sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0; fi
# 서버 기동용 사전 점검(docker·compose·데몬·자격증명). 건너뛰기: DEPLOY_SKIP_DOCTOR=1
# 운영 기본 프로젝트(deploy)를 띄울 때는 백업 설정을 필수로 본다(D88/U6). 시험·데모 프로젝트(deploy-*)는 아니다.
REQ=""; case "${1:-}" in ""|-*) REQ=--require-backup;; deploy) REQ=--require-backup;; esac
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" --up $REQ || exit 1
source "$(dirname "$0")/lib.sh"
P=deploy; case "${1:-}" in ""|-*) ;; *) P=$1; shift;; esac
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
# gateway 의 CA 볼륨은 비루트(uid 10001)가 쓸 수 있어야 한다. 이미지의 /data 는 root 소유라 처음 한 번 소유자를 바꾼다(root 로 잠깐 도는 일회성 컨테이너, 네트워크 없음).
V="${P}_gateway-data"
if ! "$DOCKER" volume inspect "$V" >/dev/null 2>&1; then
  "$DOCKER" volume create --label "com.docker.compose.project=$P" --label "com.docker.compose.volume=gateway-data" "$V" >/dev/null
  UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  "$DOCKER" run --rm --network none --user 0 --cap-drop ALL --cap-add CHOWN -v "$V:/data" "$UTIL" chown 10001:10001 /data >/dev/null || die "gateway-data 볼륨 소유자 설정 실패"
fi
dc "$P" up -d --wait "$@"
