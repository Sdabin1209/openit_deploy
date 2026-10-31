#!/usr/bin/env bash
# deploy 스크립트 공통. source 해서 쓴다.
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$DEPLOY_ROOT/.." && pwd)"
VENV="$DEPLOY_ROOT/.venv"
# 컴포넌트를 부르는 진입점(scripts/*.py)은 입력·출력을 스키마로 검증하므로 jsonschema 가 있는 deploy .venv 의 파이썬이 필요하다(ADR 0045). 작업 트리(git worktree)에서는 본 리포의 .venv 를 쓴다. 없으면 python3 (jsonschema 가 없으면 진입점이 이유를 내고 실패한다: 검증을 건너뛰지 않는다)
DEPLOY_PY="$VENV/bin/python"
if [ ! -x "$DEPLOY_PY" ]; then DEPLOY_COMMON_ROOT="$(cd "$(git -C "$DEPLOY_ROOT" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)"; DEPLOY_PY="$DEPLOY_COMMON_ROOT/.venv/bin/python"; fi
[ -x "$DEPLOY_PY" ] || DEPLOY_PY=python3
die() { echo "오류: $*" >&2; exit 1; }
# 시험 전용: 롤백 시험처럼 '같은 소스인데 다른 digest 의 새 버전'이 필요할 때 이미지에 시험 라벨 하나(openit.test-build=<ID>)를 더한다. BUILD_TEST_ID 가 없으면 아무것도 하지 않는다.
# 왜 revision 에 접미사를 붙이지 않는가: io.openit.revision 은 소스 커밋(hex)이어야 한다(영역 Dockerfile 의 형식 검사와 계약 ImageLabels 의 ^[0-9a-f]{7,40}$). revision 에 접미사(-test2)를 붙이던 예전 방식은 이 규칙과 충돌했다.
# 왜 이 라벨 키인가: ImageLabels 는 io.openit.* 의 모르는 키만 거부하고 다른 접두사는 무시한다(propertyNames). 그래서 계약 라벨은 그대로 두고 digest 만 달라진다. 운영에는 쓰지 않는다.
apply_test_label() { # apply_test_label <이미지 이름:태그>  -> 표준 출력: 사용할 이미지 이름. 시험 ID 가 있으면 새 이름 <이름:태그>-<ID> (원래 이미지는 그대로 둔다)
  [ -n "${BUILD_TEST_ID:-}" ] || { echo "$1"; return 0; }
  [[ "$BUILD_TEST_ID" =~ ^[a-z0-9][a-z0-9._-]{0,31}$ ]] || die "BUILD_TEST_ID 형식: 소문자·숫자·.·_·- (1~32자): '$BUILD_TEST_ID'"
  printf 'FROM %s\nLABEL openit.test-build=%s\n' "$1" "$BUILD_TEST_ID" | "$DOCKER" build -q -t "$1-$BUILD_TEST_ID" - >/dev/null || die "시험 라벨을 더하지 못했다: $1"
  echo "$1-$BUILD_TEST_ID"
}
# 이미지 라벨이 계약 ImageLabels 스키마를 따르는지 게시 전에 검사한다(스키마 정본은 계약 패키지의 ImageLabels: scripts/check_image_labels.py 가 패키지에서 읽는다, 사본 없음).
# 사용: validate_image_labels <이미지> [표시 이름]  -> 0 통과, 1 어긋남(사유를 표준 출력에), 2 검사를 못 함(jsonschema 없음 등: 통과로 세지 않는다).
# 왜 파이썬: 스키마(JSON Schema 2020-12) 검증을 셸로 다시 구현하지 않는다. 파이썬은 LABELS_PYTHON, 없으면 deploy .venv, 없으면 python3.
validate_image_labels() {
  local py=${LABELS_PYTHON:-$DEPLOY_ROOT/.venv/bin/python}; [ -x "$py" ] || py=python3
  "$DOCKER" image inspect "$1" --format '{{json .Config.Labels}}' | tr -d '\r' | "$py" -W ignore "$DEPLOY_ROOT/scripts/check_image_labels.py" --name "${2:-$1}"
}
# docker: 표준 `docker` CLI 하나와 설정된 데몬(DOCKER_HOST 또는 docker context) 하나의 경로만 쓴다. 다른 실행 파일은 환경 변수 DOCKER 로 지정한다.
# 환경 문제(데몬 꺼짐, 권한, 연동, 자격증명 도우미)는 코드로 숨기지 않는다: 데몬에 닿지 않으면 명확한 오류로 멈추고, 원인 진단과 고치는 법은
# scripts/doctor.sh 와 docs/SETUP.md 가 안내한다. docker 가 필요 없는 스크립트는 source 하기 전에 DEPLOY_NO_DOCKER=1 을 둔다.
detect_docker() {
  DOCKER="${DOCKER:-docker}"
  # 단언: 스크립트들은 "$DOCKER" 를 따옴표로 한 단어로 부른다. 'sudo docker' 같은 여러 단어 값은 모든 호출을 깨뜨리므로 시작할 때 거부한다(실행 파일 하나만 허용).
  case "$DOCKER" in *[[:space:]]*) die "DOCKER 는 실행 파일 하나여야 한다 ('$DOCKER'). 여러 단어(sudo docker 등)는 지원하지 않는다: 실행 파일 경로만 지정하거나 docker 그룹을 쓰라 (docs/SETUP.md).";; esac
  command -v "$DOCKER" >/dev/null 2>&1 || die "docker 실행 파일을 찾을 수 없다 ('$DOCKER'). Docker를 설치하거나 DOCKER 변수를 올바른 실행 파일로 지정하라 (docs/SETUP.md)."
  "$DOCKER" info >/dev/null 2>&1 || die "Docker 데몬에 닿지 않는다: 데몬이 떠 있는지, 현재 사용자의 접근 권한(리눅스는 docker 그룹)과 DOCKER_HOST / docker context 설정이 맞는지 확인하라. 원인 진단: bash scripts/doctor.sh, 환경별 설정: docs/SETUP.md."
}
[ "${DEPLOY_NO_DOCKER:-0}" = 1 ] || detect_docker
# 빌드가 쓰는 의존 태그: 한 곳에서 정한다(build-images.sh 와 doctor.sh 가 같은 값을 쓴다). 환경 변수로 덮어쓸 수 있다.
DEPLOY_BC_TAG="${BOUNDARY_TAG_ALL:-v3.1.2}"          # boundary-contracts: 모든 이미지(dataset-store 의 I2 서버 포함, 계약 2.1.0 부터)와 호스트 실행(E2E 클라이언트·검증기·synthetic-data 잡)이 같은 값을 쓴다
DEPLOY_MR_TAG="${MODEL_RUNTIME_TAG_ALL:-v0.11.9}"     # model-runtime: 모든 이미지가 같은 태그로 빌드된다(survey-service·release-gate·model-serving CPU/GPU, 중립 LoRA 패키지). 어긋나면 게이트가 CONTRACT_COMPAT 로 반려한다
DEPLOY_LINK_TAG="${LINK_TAG_ALL:-v0.4.3}"            # link(통신 기반 라이브러리, D118): deploy 의 Python 이 이웃을 부르는 곳(link_* 컴포넌트, E2E)이 쓴다. 영역 이미지에 어느 link 가 들어갔는지의 기록은 ADR 0046
# 노드 영역(admin-console, kiosk-frontend)의 시험·타입 검사를 호스트에서 돌리는 데 필요한 node 주 버전 하한. 두 영역의 package.json engines(">=24")와 Dockerfile(node:24)이 근거다. doctor.sh 가 읽는다
DEPLOY_NODE_MIN_MAJOR=24
DEPLOY_SS_TAG="survey-schema-v3.0.0"                 # survey-service 의 문진 스키마 태그 (question-authoring 빌드)
# 영역(리포) 목록은 head/shared/areas.json 이 정본이다. 셸에서는 이 함수 하나로 읽는다(python3 areas.py 를 부른다. 왜: jq 가 없는 호스트가 있고 셸로 JSON 을 파싱하면 깨지기 쉽다).
# 사용: areas_list [--kind python,node,library,compose,docs] [--train] [--except 이름,이름]  -> 공백으로 이은 이름. 시험용 위치: AREAS_FILE
areas_list() { "$DEPLOY_PY" -W ignore "$(dirname "${BASH_SOURCE[0]}")/areas.py" --file "${AREAS_FILE:-$WORKSPACE/head/shared/areas.json}" "$@"; }
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름(영역 목록이 아니다: model-registry 는 model-lab 영역의 이미지)
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console"
# 선택 이미지: 기본 빌드·게시 흐름에 들어가지 않는다(약 13GB). build-images.sh --gpu 로 만든다 (compose.llm.yaml)
SERVICES_OPTIONAL="model-serving-gpu"
# 서비스 -> 소스 리포·variant 대응(U42, 한 곳). build-images.sh 가 이것으로 영역 리포를 고르고 계약 BuildImageRequest 의 variant 를 채운다. 서비스 목록과 같은 자리에 둔다
service_repo() { case "$1" in model-registry) echo model-lab;; dataset-store) echo synthetic-data;; model-serving|model-serving-gpu) echo model-runtime;; *) echo "$1";; esac; }
service_variant() { case "$1" in model-serving-gpu) echo gpu;; *) echo "";; esac; }
# build/images.env 의 선택 이미지(GPU) 기록을 유지해도 되는지: gpu_record_valid <기록 파일>. 유효하면 그 줄을 stdout 으로 내고 0, 아니면 이유를 stderr 로 내고 1.
# 유효 = (1) 기록의 커밋이 현재 기준 model-runtime 태그(DEPLOY_MR_TAG)의 커밋과 같고 (2) 이미지가 로컬에 실제로 있다. 기록이 없으면 조용히 1.
# 13GB 이미지를 따로 빌드한 사용자가 있어, 맞지 않는 기록은 버리되 이미지 자체는 지우지 않는다(디스크 회수는 사용자가 판단한다).
gpu_record_valid() {
  local rec img c want
  rec=$(grep '^model-serving-gpu ' "$1" 2>/dev/null | head -1 || true); [ -n "$rec" ] || return 1
  img=$(awk '{print $2}' <<<"$rec"); c=$(awk '{print $3}' <<<"$rec")
  want=$(git -C "$WORKSPACE/model-runtime" rev-parse --short "$DEPLOY_MR_TAG^{commit}" 2>/dev/null) || { echo "GPU 이미지 기록을 버린다: model-runtime $DEPLOY_MR_TAG 의 커밋을 읽지 못했다(태그가 없다). 다시 빌드: bash scripts/build-images.sh --gpu" >&2; return 1; }
  [ "$c" = "$want" ] || { echo "GPU 이미지 기록을 버린다: 기록의 커밋 $c 는 현재 기준 model-runtime $DEPLOY_MR_TAG($want)와 다르다. 다시 빌드: bash scripts/build-images.sh --gpu (이전 이미지는 지우지 않았다)" >&2; return 1; }
  "${DOCKER:-docker}" image inspect "$img" >/dev/null 2>&1 || { echo "GPU 이미지 기록을 버린다: 이미지 $img 가 이 호스트에 없다. 다시 빌드: bash scripts/build-images.sh --gpu" >&2; return 1; }
  printf '%s\n' "$rec"
}
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
  env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST -u OPS_FEEDBACK_DIGEST -u RELEASE_GATE_DIGEST -u GATEWAY_IMAGE -u REGISTRY_IMAGE -u UTIL_IMAGE -u POSTGRES_IMAGE -u RESTIC_IMAGE -u REST_SERVER_IMAGE -u PROMETHEUS_IMAGE -u ALERTMANAGER_IMAGE -u BLACKBOX_IMAGE -u NODE_EXPORTER_IMAGE -u JSON_EXPORTER_IMAGE -u DEPLOY_REGISTRY \
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

# 비밀 파일 모드(docs/adr/0022-secret-file-permissions.md). compose 의 파일 secrets 는 호스트 소유자·모드를 그대로 마운트하고 uid/gid/mode 옵션은 적용되지 않는다
# (측정함: 호스트 소유자 600 파일은 컨테이너 uid 10001 이 읽지 못한다). 그래서 컨테이너가 읽는 파일(compose.yaml 의 secrets/configs 가 가리키는 이름)은 644(폴더 700 안),
# 호스트에서만 쓰는 파일(계정 암호·해시, 기기 토큰 원본)은 600 이다. secret_mode <이름> -> 600|644
secret_mode() {
  local n=$1
  if [ -z "${_MOUNTED_SECRETS+x}" ]; then
    _MOUNTED_SECRETS=" $(sed -n 's|^[[:space:]]*file:[[:space:]]*${SECRETS_DIR:-./secrets}/\(tokens/\)\{0,1\}\([A-Za-z0-9._-]*\).*|\2|p' "$DEPLOY_ROOT/compose.yaml" | tr '\n' ' ') "
  fi
  # compose.inference.yaml / compose.external-inference.yaml 이 가리키는 파일은 다른 호스트로 옮겨져 컨테이너가 읽는다(이름 고정)
  case "$_MOUNTED_SECRETS $n" in *" $n "*" $n") echo 644;; *) case "$n" in model-runtime-tokens|gate-read-model-serving|external-inference) echo 644;; *) echo 600;; esac;; esac
}
