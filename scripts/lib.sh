#!/usr/bin/env bash
# deploy 스크립트 공통. source 해서 쓴다.
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$DEPLOY_ROOT/.." && pwd)"
VENV="$DEPLOY_ROOT/.venv"
die() { echo "오류: $*" >&2; exit 1; }
# docker: 표준 `docker` CLI 하나와 설정된 데몬(DOCKER_HOST 또는 docker context) 하나의 경로만 쓴다. 다른 실행 파일은 환경 변수 DOCKER 로 지정한다.
# 환경 문제(데몬 꺼짐, 권한, 연동, 자격증명 도우미)는 코드로 숨기지 않는다: 데몬에 닿지 않으면 명확한 오류로 멈추고, 원인 진단과 고치는 법은
# scripts/doctor.sh 와 docs/SETUP.md 가 안내한다. docker 가 필요 없는 스크립트는 source 하기 전에 DEPLOY_NO_DOCKER=1 을 둔다.
detect_docker() {
  DOCKER="${DOCKER:-docker}"
  command -v "$DOCKER" >/dev/null 2>&1 || die "docker 실행 파일을 찾을 수 없다 ('$DOCKER'). Docker를 설치하거나 DOCKER 변수를 올바른 실행 파일로 지정하라 (docs/SETUP.md)."
  "$DOCKER" info >/dev/null 2>&1 || die "Docker 데몬에 닿지 않는다: 데몬이 떠 있는지, 현재 사용자의 접근 권한(리눅스는 docker 그룹)과 DOCKER_HOST / docker context 설정이 맞는지 확인하라. 원인 진단: bash scripts/doctor.sh, 환경별 설정: docs/SETUP.md."
}
[ "${DEPLOY_NO_DOCKER:-0}" = 1 ] || detect_docker
# 빌드가 쓰는 의존 태그: 한 곳에서 정한다(build-images.sh 와 doctor.sh 가 같은 값을 쓴다). 환경 변수로 덮어쓸 수 있다.
DEPLOY_BC_TAG="${BOUNDARY_TAG_ALL:-v1.3.3}"          # boundary-contracts (이미지 빌드, E2E 클라이언트·검증기)
DEPLOY_BC_TAG_SD="v1.2.0"                            # boundary-contracts: synthetic-data 가 고정한 태그(호스트 실행용)
DEPLOY_MR_TAG="${MODEL_RUNTIME_TAG_ALL:-v0.5.1}"     # model-runtime (survey-service·release-gate 이미지, 추론 서버)
DEPLOY_TE_TAG="v0.2.0"                               # turn-engine (영역 빌드 스크립트의 기본 태그)
DEPLOY_SS_TAG="survey-schema-v1.0.0"                 # survey-service 의 문진 스키마 태그 (question-authoring 빌드)
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry model-serving kiosk-frontend admin-console"
# 이미지 이름은 영역 이름과 같다. 로컬 레지스트리 안의 저장소 이름은 openit/<영역>.
dc() { # dc <project> <compose args...>
  local project=$1; shift
  local files=(-f "$DEPLOY_ROOT/compose.yaml")
  if [ -n "${COMPOSE_EXTRA:-}" ]; then
    for f in $COMPOSE_EXTRA; do files+=(-f "$f"); done
  fi
  local envs=(--env-file "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  [ -f "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}" ] && envs+=(--env-file "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}")
  [ -f "$DEPLOY_ROOT/.env" ] && envs+=(--env-file "$DEPLOY_ROOT/.env")
  # 잠금 파일이 digest의 유일한 출처다: 셸에 남은 같은 이름의 변수가 --env-file 을 이기지 못하게 지운다
  env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST -u OPS_FEEDBACK_DIGEST -u RELEASE_GATE_DIGEST -u GATEWAY_IMAGE -u REGISTRY_IMAGE -u UTIL_IMAGE -u DEPLOY_REGISTRY \
    "$DOCKER" compose -p "$project" --project-directory "$DEPLOY_ROOT" "${files[@]}" "${envs[@]}" "$@"
}
# 외부 추론 서버 모드(D72): external_inference_setup <URL>. INFERENCE_URL / INFERENCE_TOKEN_FILE 을 내보내고 COMPOSE_EXTRA 에 override 를 붙인다.
# 토큰은 값을 인자로 받지 않는다: 환경 변수 INFERENCE_TOKEN(여기서 600 파일로 옮긴다) 또는 INFERENCE_TOKEN_FILE(경로, 파일에 EXTERNAL_INFERENCE_TOKEN=...)
# 또는 이미 있는 $SECRETS_DIR/external-inference.env. 값은 출력하지 않는다.
external_inference_setup() {
  local url=${1:-} sd=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
  case "$url" in http://*|https://*) ;; *) die "--external-inference 에는 http:// 또는 https:// 로 시작하는 주소가 필요하다: '$url'";; esac
  case "${url#*://}" in *@*) die "주소에 계정·암호를 넣지 않는다 (토큰은 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE 로)";; esac
  if [ -n "${INFERENCE_TOKEN_FILE:-}" ]; then
    case "$INFERENCE_TOKEN_FILE" in /*) ;; *) INFERENCE_TOKEN_FILE="$PWD/$INFERENCE_TOKEN_FILE";; esac
    [ -s "$INFERENCE_TOKEN_FILE" ] || die "INFERENCE_TOKEN_FILE 이 없거나 비었다: $INFERENCE_TOKEN_FILE"
  elif [ -n "${INFERENCE_TOKEN:-}" ]; then
    mkdir -p "$sd"; chmod 700 "$sd" 2>/dev/null || true
    INFERENCE_TOKEN_FILE="$sd/external-inference.env"
    ( umask 077; printf 'EXTERNAL_INFERENCE_TOKEN=%s\n' "$INFERENCE_TOKEN" > "$INFERENCE_TOKEN_FILE" )
  elif [ -s "$sd/external-inference.env" ]; then
    INFERENCE_TOKEN_FILE="$sd/external-inference.env"
  else
    die "외부 추론 서버의 토큰이 필요하다: 환경 변수 INFERENCE_TOKEN 을 두거나, EXTERNAL_INFERENCE_TOKEN=<토큰> 한 줄이 든 파일 경로를 INFERENCE_TOKEN_FILE 로 준다 (값을 인자로 넘기지 않는다)"
  fi
  export INFERENCE_URL="$url" INFERENCE_TOKEN_FILE
  unset INFERENCE_TOKEN
  case " ${COMPOSE_EXTRA:-} " in *compose.external-inference.yaml*) ;; *) COMPOSE_EXTRA="${COMPOSE_EXTRA:+$COMPOSE_EXTRA }$DEPLOY_ROOT/compose.external-inference.yaml";; esac
  export COMPOSE_EXTRA
}
# 컨테이너 포트가 Docker가 배정한 호스트 포트를 읽는다. port_of <컨테이너> <내부포트>
port_of() { "$DOCKER" port "$1" "$2/tcp" | head -1 | tr -d '\r' | sed 's/.*://'; }
# 빈 포트를 하나 고른다. 임시 레지스트리가 push 대상 포트를 명시적으로 쓰려고 쓴다(컨테이너의 호스트 포트는 Docker가 배정한다).
free_port() {
  python3 - <<'PY'
import random, socket
for _ in range(200):
    p = random.randint(20000, 39999)
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", p)); s.close(); print(p); break
    except OSError:
        s.close()
PY
}
