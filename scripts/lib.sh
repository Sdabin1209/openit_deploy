#!/usr/bin/env bash
# deploy 스크립트 공통. source 해서 쓴다.
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 비밀 파일의 그룹 gid(L02, ADR 0054): 컨테이너가 읽는 비밀은 640 이고 이 그룹이 읽는다. compose 의 x-hardening 이 group_add 로 컨테이너 프로세스에 이 gid 를 더한다.
# 기본은 비밀을 만드는 호스트 사용자의 주 그룹(id -g): 만들 때 root 가 필요 없다. 다른 호스트로 옮기면 그 호스트의 값으로 SECRETS_GID 를 준다
export SECRETS_GID="${SECRETS_GID:-$(id -g)}"
WORKSPACE="$(cd "$DEPLOY_ROOT/.." && pwd)"
# 작업 트리(git worktree, deploy/build/wt-*)에서는 부모가 deploy/build 라 이웃 영역이 없다: 본 리포(git 공통 폴더의 부모)의 부모를 워크스페이스로 쓴다
[ -f "$DEPLOY_ROOT/.git" ] && { _c=$(git -C "$DEPLOY_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && WORKSPACE="$(cd "$_c/../.." && pwd)"; }; unset _c
VENV="$DEPLOY_ROOT/.venv"
# 컴포넌트를 부르는 진입점(scripts/*.py)은 입력·출력을 스키마로 검증하므로 jsonschema 가 있는 deploy .venv 의 파이썬이 필요하다(ADR 0045). 작업 트리(git worktree)에서는 본 리포의 .venv 를 쓴다. 없으면 python3 (jsonschema 가 없으면 진입점이 이유를 내고 실패한다: 검증을 건너뛰지 않는다)
DEPLOY_PY="$VENV/bin/python"
if [ ! -x "$DEPLOY_PY" ]; then DEPLOY_COMMON_ROOT="$(cd "$(git -C "$DEPLOY_ROOT" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)"; DEPLOY_PY="$DEPLOY_COMMON_ROOT/.venv/bin/python"; fi
# 왜 시스템 python3 로 조용히 넘어가지 않는가: 거기엔 계약 패키지(boundary_contracts)가 없어 점검이 엉뚱한 이유로 실패한다(TLS worktree 에서 "시험 빌드 라벨" 점검이 그렇게 죽었다). 환경 문제는 코드로 숨기지 않고 고칠 방법을 말하며 멈춘다.
deploy_py() { [ -x "$DEPLOY_PY" ] || { echo "오류: deploy .venv 가 없다: bash scripts/prepare-areas.sh (docs/SETUP.md)" >&2; exit 1; }; printf '%s\n' "$DEPLOY_PY"; }
# 레지스트리 주소의 스킴: loopback(127.x, localhost, ::1)이면 http, 아니면 https. 계약 3.4.1 클라이언트의 규칙(loopback 밖 평문 http 거부)과 같고, Docker 도 loopback 밖 평문 레지스트리는
# insecure-registries 설정 없이는 거부한다. 같은 호스트 안의 로컬 레지스트리(registry:2, 인증·TLS 없음)는 loopback 에만 게시한다(compose.registry.yaml).
registry_scheme() { local h=${1%%/*}; h=${h%:*}; case "$h" in 127.*|localhost|\[::1\]|::1) echo http;; *) echo https;; esac; }
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
# 왜 파이썬: 스키마(JSON Schema 2020-12) 검증을 셸로 다시 구현하지 않는다. 파이썬은 LABELS_PYTHON, 없으면 deploy .venv, 없으면 멈춘다(python3 로 넘어가지 않는다).
validate_image_labels() {
  local py=${LABELS_PYTHON:-}; [ -n "$py" ] || py=$(deploy_py) || return 1
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
DEPLOY_BC_TAG="${BOUNDARY_TAG_ALL:-v3.4.13}"          # boundary-contracts: 모든 이미지(dataset-store 의 I2 서버 포함, 계약 2.1.0 부터)와 호스트 실행(E2E 클라이언트·검증기·synthetic-data 잡)이 같은 값을 쓴다
DEPLOY_MR_TAG="${MODEL_RUNTIME_TAG_ALL:-v0.11.21}"     # model-runtime: 모든 이미지가 같은 태그로 빌드된다(survey-service·release-gate·model-serving CPU/GPU, 중립 LoRA 패키지). 어긋나면 게이트가 CONTRACT_COMPAT 로 반려한다
DEPLOY_LINK_TAG="${LINK_TAG_ALL:-v0.4.19}"            # link(통신 기반 라이브러리, D118): deploy 의 Python 이 이웃을 부르는 곳(link_* 컴포넌트, E2E)이 쓴다. 영역 이미지에 어느 link 가 들어갔는지의 기록은 ADR 0046
# 노드 영역(admin-console, kiosk-frontend)의 시험·타입 검사를 호스트에서 돌리는 데 필요한 node 주 버전 하한. 두 영역의 package.json engines(">=24")와 Dockerfile(node:24)이 근거다. doctor.sh 가 읽는다
DEPLOY_NODE_MIN_MAJOR=24
DEPLOY_SS_TAG="survey-schema-v4.1.1"                 # survey-service 의 문진 스키마 태그 (question-authoring 빌드)
# 영역(리포) 목록은 head/shared/areas.json 이 정본이다. 셸에서는 이 함수 하나로 읽는다(python3 areas.py 를 부른다. 왜: jq 가 없는 호스트가 있고 셸로 JSON 을 파싱하면 깨지기 쉽다).
# 사용: areas_list [--kind python,node,library,compose,docs] [--train] [--except 이름,이름]  -> 공백으로 이은 이름. 시험용 위치: AREAS_FILE
areas_list() { "$DEPLOY_PY" -W ignore "$(dirname "${BASH_SOURCE[0]}")/areas.py" --file "${AREAS_FILE:-$WORKSPACE/head/shared/areas.json}" "$@"; }
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름(영역 목록이 아니다: model-registry 는 model-lab 영역의 이미지)
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console area-gateway backup-store public-ingress step-ca monitoring identity identity-proxy identity-db survey-db question-authoring-db ops-feedback-db release-gate-db"
# 선택 이미지: 기본 빌드·게시 흐름에 들어가지 않는다(약 13GB). build-images.sh --gpu 로 만든다 (compose.llm.yaml)
SERVICES_OPTIONAL="model-serving-gpu"   # 선택 이미지: 기본 빌드에 넣지 않는다(13GB)
# 서비스 -> 소스 리포·variant 대응(U42, 한 곳). build-images.sh 가 이것으로 영역 리포를 고르고 계약 BuildImageRequest 의 variant 를 채운다. 서비스 목록과 같은 자리에 둔다
service_repo() { case "$1" in area-gateway|public-ingress|monitoring|backup-store|step-ca|identity|identity-proxy|identity-db) echo platform;; survey-db) echo survey-service;; question-authoring-db) echo question-authoring;; ops-feedback-db) echo ops-feedback;; release-gate-db) echo release-gate;; model-registry) echo model-lab;; dataset-store) echo synthetic-data;; model-serving|model-serving-gpu) echo model-runtime;; *) echo "$1";; esac; }
service_variant() { case "$1" in model-serving-gpu) echo gpu;; public-ingress|monitoring|backup-store|step-ca|identity|identity-proxy|identity-db) echo "$1";; survey-db|question-authoring-db|ops-feedback-db|release-gate-db) echo db;; *) echo "";; esac; }
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
# 밖에서 보이는 주소(U82, ADR 0057): 첫 GATEWAY_HOSTS 이름 + 밖에 보이는 HTTPS 포트(GATEWAY_PUBLIC_TLS_PORT, 기본 8443; 443 이면 생략). Keycloak 의 발급자(iss)와 oauth2-proxy 의 로그인·콜백 주소가 이 한 곳에서 나온다.
# 사람 화면(직원·승인·검토·저작·admin)은 이 이름으로 연다: 다른 이름으로 열면 로그인 쿠키가 이 이름에만 생긴다
gateway_public_url() {
  local first=${GATEWAY_HOSTS:-localhost:8443, 127.0.0.1:8443} p=${GATEWAY_PUBLIC_TLS_PORT:-8443}
  first=${first%%,*}; first=${first// /}; first=${first%:*}
  [[ "$first" =~ ^[A-Za-z0-9.-]+$ ]] || die "GATEWAY_HOSTS 첫 항목의 호스트 이름 규칙 위반: '$first'"
  [[ "$p" =~ ^[0-9]{2,5}$ ]] || die "GATEWAY_PUBLIC_TLS_PORT 형식 위반: '$p'"
  if [ "$p" = 443 ]; then echo "https://$first"; else echo "https://$first:$p"; fi
}
export GATEWAY_PUBLIC_URL="$(gateway_public_url)"
# pg-tls 볼륨(postgres 서버 인증서·키, ADR 0060)은 postgres 의 uid(999)가 쓸 수 있어야 한다(새 이름 있는 볼륨은 root 소유). gateway-data 와 같은 방식으로 처음 한 번 소유자를 맞춘다. dc 가 up/run 때 부른다
ensure_pg_tls_volume() { # ensure_pg_tls_volume <프로젝트>: 영역 DB 마다 서버 인증서 볼륨(<서비스>-pgtls)의 소유자를 postgres(999)로 맞춘다
  local svc V UTIL
  for svc in survey-db question-authoring-db ops-feedback-db release-gate-db keycloak-db; do
    V="${1}_${svc}-pgtls"
    "$DOCKER" volume inspect "$V" >/dev/null 2>&1 && continue
    "$DOCKER" volume create --label "com.docker.compose.project=$1" --label "com.docker.compose.volume=${svc}-pgtls" "$V" >/dev/null || return 1
    UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
    "$DOCKER" run --network none --user 0 --cap-drop ALL --cap-add CHOWN --rm -v "$V:/data" "$UTIL" chown 999:999 /data >/dev/null || die "$svc 서버 인증서 볼륨 소유자 설정 실패"
  done
}
# 잡 덧씌우기 파일은 프로젝트마다 따로 둔다(다른 프로젝트·시험의 compose 에 없는 잡 서비스를 가리키면 compose 가 거부한다): JOBS_OVERLAY 로 바꿀 수 있다
jobs_overlay_path() { echo "${JOBS_OVERLAY:-$DEPLOY_ROOT/state/compose.jobs.${1:?프로젝트}.yaml}"; }
# 이미지 라벨에서 만드는 배치 입력(영역 게이트웨이의 exposure.json, 잡 덧씌우기)을 만든다: gen_stack_files <프로젝트>. 기동 때마다 새로 만든다(이미지가 바뀌면 라벨도 바뀐다)
gen_stack_files() {
  local project=$1 cfg
  cfg=$(mktemp); rm -f "$(jobs_overlay_path "$project")"   # 이전 덧씌우기가 아래 config 입력에 섞이지 않게
  GEN_STACK_ACTIVE=1 dc "$project" --profile jobs --profile local-inference config --format json > "$cfg"   # local-inference: 외부 추론 모드에서 꺼진 model-serving 의 선언도 만든다(다른 호스트의 추론 서버가 같은 선언을 쓴다) || { rm -f "$cfg"; return 1; }
  mkdir -p "$DEPLOY_ROOT/state"
  "$DEPLOY_PY" "$DEPLOY_ROOT/scripts/gen-jobs.py" --out "$(jobs_overlay_path "$project")" --compose-json "$cfg" >/dev/null || { rm -f "$cfg"; return 1; }
  "$DEPLOY_PY" "$DEPLOY_ROOT/scripts/gen-gateways.py" --out "${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}" --compose-json "$cfg" >/dev/null || { rm -f "$cfg"; return 1; }
  rm -f "$cfg"
}
dc() { # dc <project> <compose args...>
  local project=$1; shift
  case " $* " in *" up "*|*" run "*) [ -n "${DOCKER:-}" ] && ensure_pg_tls_volume "$project";; esac
  # 라벨에서 만드는 입력(영역 게이트웨이 exposure.json, 잡 덧씌우기)은 기동 때 만든다(배치된 서버에는 생성기가 없다: 지휘 기계가 만든 파일을 플레이북이 state/ 로 건넨다). 영역 DB 만 띄우는 단독 시험처럼 그 입력이 필요 없는 호출은 DEPLOY_NO_STACK_FILES=1 로 건너뛴다(이미지를 받지 않으려는 것이다)
  if [ -z "${GEN_STACK_ACTIVE:-}" ] && [ -z "${DEPLOY_NO_STACK_FILES:-}" ] && [ -f "$DEPLOY_ROOT/scripts/gen-gateways.py" ] && [ -n "${DOCKER:-}" ] && case " $* " in *" up "*|*" run "*|*" create "*) true;; *) false;; esac; then
    GEN_STACK_ACTIVE=1 gen_stack_files "$project" || die "이미지 라벨에서 배치 입력(영역 게이트웨이 exposure.json, 잡 덧씌우기)을 만들지 못했다"
  fi
  local files=(-f "$DEPLOY_ROOT/compose.yaml")
  if [ -n "${COMPOSE_EXTRA:-}" ]; then
    for f in $COMPOSE_EXTRA; do files+=(-f "$f"); done
  fi
  # 잡 서비스의 command·시간 한도는 이미지 라벨 io.openit.jobs 에서 만든 덧씌우기 파일이 정한다(S10, scripts/gen-jobs.py). 있으면 맨 뒤에 얹는다
  [ -f "$(jobs_overlay_path "$project")" ] && files+=(-f "$(jobs_overlay_path "$project")")
  local envs=(--env-file "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  [ -f "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}" ] && envs+=(--env-file "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}")
  [ -f "$DEPLOY_ROOT/.env" ] && envs+=(--env-file "$DEPLOY_ROOT/.env")
  # 잠금 파일이 digest의 유일한 출처다: 셸에 남은 같은 이름의 변수가 --env-file 을 이기지 못하게 지운다
  env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST -u OPS_FEEDBACK_DIGEST -u RELEASE_GATE_DIGEST -u GATEWAY_IMAGE -u REGISTRY_IMAGE -u UTIL_IMAGE -u POSTGRES_IMAGE -u RESTIC_IMAGE -u REST_SERVER_IMAGE -u PROMETHEUS_IMAGE -u ALERTMANAGER_IMAGE -u BLACKBOX_IMAGE -u NODE_EXPORTER_IMAGE -u JSON_EXPORTER_IMAGE -u KEYCLOAK_IMAGE -u OAUTH2_PROXY_IMAGE -u STEP_CA_IMAGE -u PAUSE_IMAGE -u DEPLOY_REGISTRY "DEVICE_CA_FILE=${DEVICE_CA_FILE:-${SECRETS_DIR:-$DEPLOY_ROOT/secrets}/device-ca.pem}" "GATEWAY_PUBLIC_URL=$(gateway_public_url)" "HF_CACHE_VOLUME=$HF_CACHE_VOLUME" \
    "$DOCKER" compose -p "$project" --project-directory "$DEPLOY_ROOT" "${files[@]}" "${envs[@]}" "$@"
}
# 외부 추론 서버 모드(D72): external_inference_setup <URL>. INFERENCE_URL / INFERENCE_TOKEN_FILE 을 내보내고 COMPOSE_EXTRA 에 override 를 붙인다.
# 토큰은 값을 인자로 받지 않는다: 환경 변수 INFERENCE_TOKEN(여기서 파일로 옮긴다) 또는 INFERENCE_TOKEN_FILE(경로, 파일 내용이 토큰 하나, D84)
# 또는 이미 있는 $SECRETS_DIR/tokens/external-inference. 파일은 compose 가 secrets 로 마운트한다(컨테이너 환경 변수로 넣지 않는다). 값은 출력하지 않는다.
external_inference_setup() {
  local url=${1:-} sd=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
  case "$url" in https://*) ;; *) die "--external-inference 에는 https:// 로 시작하는 주소만 받는다(평문 http 는 거부, ADR 0060): '$url'";; esac
  case "${url#*://}" in *@*) die "주소에 계정·암호를 넣지 않는다 (토큰은 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE 로)";; esac
  if [ -n "${INFERENCE_TOKEN_FILE:-}" ]; then
    case "$INFERENCE_TOKEN_FILE" in /*) ;; *) INFERENCE_TOKEN_FILE="$PWD/$INFERENCE_TOKEN_FILE";; esac
    [ -s "$INFERENCE_TOKEN_FILE" ] || die "INFERENCE_TOKEN_FILE 이 없거나 비었다: $INFERENCE_TOKEN_FILE"
    ! grep -q '^EXTERNAL_INFERENCE_TOKEN=' "$INFERENCE_TOKEN_FILE" || die "INFERENCE_TOKEN_FILE 형식이 바뀌었다(D84): 파일 내용은 EXTERNAL_INFERENCE_TOKEN=<토큰> 줄이 아니라 토큰 값 하나여야 한다"
  elif [ -n "${INFERENCE_TOKEN:-}" ]; then
    mkdir -p "$sd/tokens"; chmod 700 "$sd" "$sd/tokens" 2>/dev/null || true
    INFERENCE_TOKEN_FILE="$sd/tokens/external-inference"
    ( umask 027; printf '%s\n' "$INFERENCE_TOKEN" > "$INFERENCE_TOKEN_FILE" ); chgrp "$SECRETS_GID" "$INFERENCE_TOKEN_FILE" 2>/dev/null || true   # 640 + 그룹 SECRETS_GID: 컨테이너는 group_add 로 읽는다(R6.3). 폴더가 700
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
# export 하지 않는다: 환경에 남으면 영역 시험(check-all 이 돌리는 model-runtime 의 run_session 시험)이 ModelServingEnv 에 없는 변수 HF_CACHE_VOLUME 을 거부해 실패했다(D7c). compose 에는 dc 가 넘긴다
HF_CACHE_VOLUME="${HF_CACHE_VOLUME:-deploy-llm-hf-cache}"
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
# 영역마다 자기 DB 컨테이너(<서비스>-db)가 있다: 데이터베이스(=계정 이름) -> compose 서비스 이름. 다른 영역의 DB 와 섞이지 않는다
pg_service_of() { case "$1" in survey) echo survey-db;; qa) echo question-authoring-db;; ops_log|ops_failure) echo ops-feedback-db;; gate) echo release-gate-db;; keycloak) echo keycloak-db;; *) return 1;; esac; }
PG_SERVICES="survey-db question-authoring-db ops-feedback-db release-gate-db keycloak-db"
# 영역 DB 서버 컨테이너 이름: pg_container <프로젝트> <DB 서비스 이름>. 떠 있지 않으면 빈 문자열
pg_container() {
  "$DOCKER" ps -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.service=${2:?DB 서비스 이름}" --filter status=running | head -1 | tr -d '\r'
}
PG_APP_DBS="ops_log ops_failure"   # 앱 계정(<이름>_app, DML만, L08)을 따로 두는 데이터베이스: 소유자 계정은 스키마를 만드는 admin migrate 전용
PG_DBS="survey qa ops_log ops_failure gate identity"   # 데이터베이스 = 계정 이름(config/postgres/initdb/10-roles.sh 의 기본값과 같다)

# 비밀 파일 모드(docs/adr/0022-secret-file-permissions.md, 0054). compose 의 파일 secrets/configs 는 호스트 소유자·그룹·모드를 그대로 마운트하고 uid/gid/mode 옵션은 적용되지 않는다.
# 컨테이너가 읽는 파일(compose.yaml 의 secrets/configs 가 가리키는 이름)은 640 + 파일 그룹 SECRETS_GID, 컨테이너는 group_add 로 그 그룹을 더해 읽는다(0054). 폴더는 700.
# 다른 호스트의 추론 서버가 읽는 파일 셋(model-runtime-tokens, gate-read-model-serving, external-inference)도 640 + 그룹이다(RUNTIME.md R6.3): 추론 compose 의 group_add(SECRETS_GID)가 읽는다. 누구나 읽게(644) 하지 않는다.
# 호스트에서만 쓰는 파일(계정 암호·해시, 기기 토큰 원본)은 600 이다. secret_mode <이름> -> 600|640
secret_mode() {
  local n=$1
  if [ -z "${_MOUNTED_SECRETS+x}" ]; then
    _MOUNTED_SECRETS=" $(sed -n 's|^[[:space:]]*file:[[:space:]]*${SECRETS_DIR:-./secrets}/\(tokens/\)\{0,1\}\([A-Za-z0-9._-]*\).*|\2|p' "$DEPLOY_ROOT/compose.yaml" | tr '\n' ' ') "
  fi
  case "$n" in external-inference) echo 640; return;; esac   # compose.external-inference.yaml 의 비밀(survey-service 가 마운트): compose.yaml 의 file: 줄에 없어도 컨테이너가 읽는다
  case "$_MOUNTED_SECRETS" in *" $n "*) echo 640;; *) echo 600;; esac
}
# 비밀 파일 하나의 모드와 그룹을 규칙대로 맞춘다: secret_fix <파일> [이름]. 640 이면 그룹을 SECRETS_GID 로 바꾼다(속한 그룹이면 root 없이 된다. 못 바꾸면 이유를 낸다)
secret_fix() {
  local f=$1 n=${2:-$(basename "$1")} m; m=$(secret_mode "$n"); chmod "$m" "$f"
  if [ "$m" = 640 ] && [ "$(stat -c %g "$f")" != "$SECRETS_GID" ]; then chgrp "$SECRETS_GID" "$f" 2>/dev/null || echo "경고: $n 의 그룹을 $SECRETS_GID 로 바꾸지 못했다(그 그룹의 구성원이어야 한다)" >&2; fi
}

# 게이트웨이 설정을 시험할 때 쓰는 TLS 재료(ADR 0060): 일회용 루트 CA 와 상류 이름용 잎 인증서를 만든다(제품 PKI 는 step-ca 이고 이것은 시험 폴더 안에만 있다).
# 사용: gateway_test_pki <빈 폴더> <상류 이름...>. 폴더에 root_ca.crt, leaf.crt, leaf.key 가 생긴다. 게이트웨이 컨테이너에는 gateway_test_mounts 가 주는 -v/-e 인자를 붙인다.
gateway_test_pki() {
  local d=$1; shift; local san="" n
  for n in "$@"; do san+="${san:+,}DNS:$n"; done
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$d/root.key" -out "$d/root_ca.crt" -subj "/CN=openit-test-root" -days 2 >/dev/null 2>&1 || return 1
  openssl req -newkey rsa:2048 -nodes -keyout "$d/leaf.key" -out "$d/leaf.csr" -subj "/CN=openit-test-leaf" >/dev/null 2>&1 || return 1
  printf 'subjectAltName=%s\n' "$san" > "$d/san.ext"
  openssl x509 -req -in "$d/leaf.csr" -CA "$d/root_ca.crt" -CAkey "$d/root.key" -CAcreateserial -out "$d/leaf.crt" -days 2 -extfile "$d/san.ext" >/dev/null 2>&1 || return 1
  chmod 644 "$d"/*
}
gateway_test_mounts() { # gateway_test_mounts <gateway_test_pki 폴더>: 게이트웨이 컨테이너에 더할 인자(루트 인증서, TLS 출처 조각)
  printf '%s\n' -v "$DEPLOY_ROOT/config/gateway-tls:/etc/caddy/gateway-tls:ro" -v "$1/root_ca.crt:/etc/openit/pki/root_ca.crt:ro" -e GATEWAY_TLS_MODE=internal
}
