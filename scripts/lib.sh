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
DEPLOY_BC_TAG="${BOUNDARY_TAG_ALL:-v2.0.2}"          # boundary-contracts (이미지 빌드, E2E 클라이언트·검증기)
DEPLOY_BC_TAG_SD="v2.0.2"                            # boundary-contracts: synthetic-data 가 고정한 태그(호스트 실행용, requirements.lock)
DEPLOY_MR_TAG="${MODEL_RUNTIME_TAG_ALL:-v0.7.2}"     # model-runtime: 모든 이미지가 같은 태그로 빌드된다(survey-service·release-gate·model-serving CPU/GPU, 중립 LoRA 패키지). 어긋나면 게이트가 CONTRACT_COMPAT 로 반려한다
# 노드 영역(admin-console, kiosk-frontend)의 시험·타입 검사를 호스트에서 돌리는 데 필요한 node 주 버전 하한. 두 영역의 package.json engines(">=24")와 Dockerfile(node:24)이 근거다. doctor.sh 가 읽는다
DEPLOY_NODE_MIN_MAJOR=24
DEPLOY_TE_TAG="${TURN_ENGINE_TAG_ALL:-v0.4.0}"          # turn-engine (survey-service·release-gate 빌드와 model-serving 이미지 라벨)
export DEPLOY_TE_TAG
DEPLOY_SS_TAG="survey-schema-v1.0.0"                 # survey-service 의 문진 스키마 태그 (question-authoring 빌드)
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry model-serving kiosk-frontend admin-console"
# 선택 이미지: 기본 빌드·게시 흐름에 들어가지 않는다(약 13GB). build-images.sh --gpu 로 만든다 (compose.llm.yaml)
SERVICES_OPTIONAL="model-serving-gpu"
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
  env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST -u OPS_FEEDBACK_DIGEST -u RELEASE_GATE_DIGEST -u GATEWAY_IMAGE -u REGISTRY_IMAGE -u UTIL_IMAGE -u POSTGRES_IMAGE -u DEPLOY_REGISTRY \
    "$DOCKER" compose -p "$project" --project-directory "$DEPLOY_ROOT" "${files[@]}" "${envs[@]}" "$@"
}
# 외부 추론 서버 모드(D72): external_inference_setup <URL>. INFERENCE_URL / INFERENCE_TOKEN_FILE 을 내보내고 COMPOSE_EXTRA 에 override 를 붙인다.
# 토큰은 값을 인자로 받지 않는다: 환경 변수 INFERENCE_TOKEN(여기서 파일로 옮긴다) 또는 INFERENCE_TOKEN_FILE(경로, 파일 내용이 토큰 하나, D84)
# 또는 이미 있는 $SECRETS_DIR/tokens/external-inference. 파일은 compose 가 secrets 로 마운트한다(컨테이너 환경 변수로 넣지 않는다). 값은 출력하지 않는다.
external_inference_setup() {
  local url=${1:-} sd=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
  case "$url" in http://*|https://*) ;; *) die "--external-inference 에는 http:// 또는 https:// 로 시작하는 주소가 필요하다: '$url'";; esac
  case "${url#*://}" in *@*) die "주소에 계정·암호를 넣지 않는다 (토큰은 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE 로)";; esac
  if [ -n "${INFERENCE_TOKEN_FILE:-}" ]; then
    case "$INFERENCE_TOKEN_FILE" in /*) ;; *) INFERENCE_TOKEN_FILE="$PWD/$INFERENCE_TOKEN_FILE";; esac
    [ -s "$INFERENCE_TOKEN_FILE" ] || die "INFERENCE_TOKEN_FILE 이 없거나 비었다: $INFERENCE_TOKEN_FILE"
    ! grep -q '^EXTERNAL_INFERENCE_TOKEN=' "$INFERENCE_TOKEN_FILE" || die "INFERENCE_TOKEN_FILE 형식이 바뀌었다(D84): 파일 내용은 EXTERNAL_INFERENCE_TOKEN=<토큰> 줄이 아니라 토큰 값 하나여야 한다"
  elif [ -n "${INFERENCE_TOKEN:-}" ]; then
    mkdir -p "$sd/tokens"; chmod 700 "$sd" "$sd/tokens" 2>/dev/null || true
    INFERENCE_TOKEN_FILE="$sd/tokens/external-inference"
    ( umask 022; printf '%s\n' "$INFERENCE_TOKEN" > "$INFERENCE_TOKEN_FILE" )   # 644: 컨테이너(uid 10001)가 읽는다. 폴더가 700
  elif [ -s "$sd/tokens/external-inference" ]; then
    INFERENCE_TOKEN_FILE="$sd/tokens/external-inference"
  else
    die "외부 추론 서버의 토큰이 필요하다: 환경 변수 INFERENCE_TOKEN 을 두거나, 토큰 하나가 든 파일의 경로를 INFERENCE_TOKEN_FILE 로 준다 (값을 인자로 넘기지 않는다)"
  fi
  export INFERENCE_URL="$url" INFERENCE_TOKEN_FILE
  unset INFERENCE_TOKEN
  case " ${COMPOSE_EXTRA:-} " in *compose.external-inference.yaml*) ;; *) COMPOSE_EXTRA="${COMPOSE_EXTRA:+$COMPOSE_EXTRA }$DEPLOY_ROOT/compose.external-inference.yaml";; esac
  export COMPOSE_EXTRA
}
# Hugging Face 캐시 볼륨(실제 LLM): 프로젝트 밖 이름 있는 볼륨이라 down/reset/--purge 가 지우지 않는다. 지우기는 명시적 확인으로만.
export HF_CACHE_VOLUME="${HF_CACHE_VOLUME:-deploy-llm-hf-cache}"
hf_cache_exists() { "$DOCKER" volume inspect "$HF_CACHE_VOLUME" >/dev/null 2>&1; }
hf_cache_size() { "$DOCKER" system df -v 2>/dev/null | tr -d '\r' | awk -v n="$HF_CACHE_VOLUME" '$1==n{print $NF; exit}'; }   # docker system df -v 표의 SIZE 열(출력 형식 의존: 못 읽으면 빈 값)
hf_cache_ensure() { hf_cache_exists || "$DOCKER" volume create --label io.openit.purpose=hf-cache "$HF_CACHE_VOLUME" >/dev/null; }
hf_cache_report() { # 상태 한 줄(없으면 아무것도 안 낸다)
  hf_cache_exists || return 0
  echo "HF 캐시 볼륨 $HF_CACHE_VOLUME: 크기 $(hf_cache_size | grep . || echo '알 수 없음') (프로젝트 밖 볼륨: down 해도 남는다. 다음 --llm up 이 모델을 다시 받지 않는다. 지우기: scripts/down.sh --purge-hf-cache)"
}
hf_cache_purge() { # hf_cache_purge <확인 완료 0|1>
  hf_cache_exists || { echo "HF 캐시 볼륨($HF_CACHE_VOLUME)이 없다."; return 0; }
  echo "지울 볼륨: $HF_CACHE_VOLUME (크기 $(hf_cache_size | grep . || echo '알 수 없음')). 지우면 다음 --llm up 이 모델(약 4GB, Qwen3-1.7B 계산값, 측정 전)을 다시 받는다. 되돌릴 수 없다."
  if [ "${1:-0}" != 1 ]; then
    if [ -t 0 ]; then printf '계속하려면 볼륨 이름 "%s" 을(를) 그대로 입력: ' "$HF_CACHE_VOLUME"; read -r ans; [ "$ans" = "$HF_CACHE_VOLUME" ] || { echo "취소했다." >&2; return 1; }
    else echo "비대화형이다. 진행하려면 --yes-purge-$HF_CACHE_VOLUME 을 명시하라." >&2; return 1; fi
  fi
  "$DOCKER" volume rm "$HF_CACHE_VOLUME" >/dev/null && echo "HF 캐시 볼륨을 지웠다. (Docker Desktop은 볼륨을 지워도 디스크 파일이 줄지 않을 수 있다)"
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
# PostgreSQL 서버 컨테이너 이름: pg_container <프로젝트>. 떠 있지 않으면 빈 문자열
pg_container() {
  "$DOCKER" ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=postgres" --filter status=running | head -1 | tr -d '\r'
}
PG_DBS="survey qa ops_log ops_failure gate"   # 데이터베이스 = 계정 이름(config/postgres/initdb/10-roles.sh 의 기본값과 같다)
