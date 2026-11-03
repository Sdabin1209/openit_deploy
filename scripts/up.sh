#!/usr/bin/env bash
# 사용: up.sh <프로젝트> [--external-inference <URL>] [compose up 인자...]   기본 프로젝트는 deploy. 시험(E2E)은 COMPOSE_EXTRA 로 설정값 overlay(test/compose.sandbox.yaml)만 더한다: 시험용 문을 내는 overlay 는 없다(docs/adr/0049).
#   --external-inference <URL>   이 구성의 model-serving 을 끄고 그 주소의 추론 서버를 쓴다(compose.external-inference.yaml, D72).
#                                토큰은 환경 변수 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE(경로)로 준다. 값을 인자로 받지 않는다.
set -euo pipefail
if [ "${1:-}" = -h ] || [ "${1:-}" = --help ]; then sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0; fi
# 서버 기동용 사전 점검(docker·compose·데몬·자격증명). 건너뛰기: DEPLOY_SKIP_DOCTOR=1
source "$(dirname "$0")/lib.sh"
P=deploy; case "${1:-}" in ""|-*) ;; *) P=$1; shift;; esac
# 운영 프로젝트(deploy)는 백업 설정이 없으면 기동하지 않는다(D88 U6). 시험 프로젝트(deploy-e2e-* 등)는 건너뛴다.
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" --up $([ "$P" = deploy ] && echo --backup --production) || exit 1
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
# pg-tls 볼륨(postgres 서버 인증서·키, ADR 0060)도 같은 이유로 postgres 의 uid(999)가 쓸 수 있어야 한다
V="${P}_pg-tls"
if ! "$DOCKER" volume inspect "$V" >/dev/null 2>&1; then
  "$DOCKER" volume create --label "com.docker.compose.project=$P" --label "com.docker.compose.volume=pg-tls" "$V" >/dev/null
  UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  "$DOCKER" run --network none --user 0 --cap-drop ALL --cap-add CHOWN --rm -v "$V:/data" "$UTIL" chown 999:999 /data >/dev/null || die "pg-tls 볼륨 소유자 설정 실패"
fi
# R7: 컨테이너에 주입하는 환경과 배치하는 설정을 기동 전에 계약(SurveyServiceEnv, OpsFeedbackServerEnv, QuestionAuthoringDeployInterface, OpsFeedbackJobConfig)으로 검증한다. 어기면 기동하지 않는다(값은 출력하지 않는다)
CFGJ=$(mktemp); CFGE=$(mktemp); trap 'rm -f "$CFGJ" "$CFGE"' EXIT
# compose 설정을 못 읽으면(필수 변수 누락 등) 그 사유가 계약 점검의 JSON 오류에 묻히지 않게 먼저 보인다
dc "$P" config --format json > "$CFGJ" 2> "$CFGE" || { echo "docker compose config 실패:" >&2; tail -5 "$CFGE" >&2; die "compose 설정을 해석하지 못했다"; }
"$DEPLOY_PY" -W ignore "$DEPLOY_ROOT/scripts/check_config_contracts.py" --compose-json "$CFGJ" || die "설정·환경이 계약을 어긴다: 기동하지 않는다(위 FAIL 의 서비스·위치를 고친다)"
# Keycloak 의 realm 가져오기 파일(허용 리다이렉트 URI 가 GATEWAY_HOSTS 에서 나온다). 없는 파일을 마운트하면 Docker 가 빈 디렉터리를 만들어 버리므로 기동 전에 만든다(ADR 0057)
bash "$DEPLOY_ROOT/scripts/gen-keycloak-realm.sh" "${SECRETS_DIR:-$DEPLOY_ROOT/secrets}/keycloak-realm.json" >/dev/null || die "Keycloak realm 파일을 만들지 못했다"
dc "$P" up -d --wait "$@"
