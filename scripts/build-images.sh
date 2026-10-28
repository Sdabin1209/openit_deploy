#!/usr/bin/env bash
# 다섯 서비스 이미지를 로컬에서 빌드한다(D22). 이웃 리포지토리는 수정하지 않는다:
#  - 영역 리포지토리는 `git archive HEAD`로 build/ctx/<이름>/ 에 꺼내 거기서 빌드한다.
#  - 라이브러리(boundary-contracts, turn-engine, model-runtime)는 영역들의 빌드 스크립트가 `git -C ../<이름> archive <태그>`로
#    읽으므로 build/ctx/<이름>/ 에 bare 사본을 둔다(태그 시점 소스만 쓰인다). 태그는 각 영역 스크립트의 기본값을 따른다.
# 이미지 이름: survey-service question-authoring ops-feedback release-gate model-registry(소스는 model-lab 리포지토리) dataset-store(소스는 synthetic-data 리포지토리)
# 결과: build/images.env (영역 로컬이름 커밋). 레지스트리에 올리고 digest 잠금을 만드는 일은 publish-images.sh.
# 사용: build-images.sh [--gpu [--yes-large]] [이름 ...]   (이름이 없으면 기본 8개 전부)
#  --gpu        model-serving 의 GPU 변형을 별도 이미지 model-serving-gpu 로 빌드한다(약 13GB, 기본 빌드에는 넣지 않는다).
#               --gpu 만 주면 GPU 이미지만 빌드한다(다른 빌드 결과를 지우지 않는다). 빌드 전에 docker system df 로 사용량과 추가 용량을 안내한다.
#  --yes-large  비대화형(터미널이 아닐 때)에서 큰 빌드를 진행한다는 확인. 없으면 비대화형은 멈춘다
#  BUILD_SUFFIX: 시험 전용. COMMIT 라벨 뒤에 붙여 다른 digest를 만든다(롤백 시험). 운영에는 쓰지 않는다.
set -euo pipefail
DEPLOY_NO_DOCKER=1   # 옵션·인자 검사는 Docker 없이도 동작한다. 데몬 감지는 그 뒤에 한다
source "$(dirname "$0")/lib.sh"
CTX="$DEPLOY_ROOT/build/ctx"
GPU=0; YES_LARGE=0; NAMES=()
for a in "$@"; do case "$a" in
  --gpu) GPU=1;; --yes-large) YES_LARGE=1;;
  -h|--help) sed -n '8,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  -*) die "알 수 없는 옵션: $a (사용: build-images.sh [--gpu [--yes-large]] [이름 ...])";;
  *) NAMES+=("$a");; esac; done
detect_docker
if [ $GPU = 1 ]; then
  [ ${#NAMES[@]} -gt 0 ] || NAMES=(model-serving-gpu)   # --gpu 단독: GPU 이미지만
  case " ${NAMES[*]} " in *" model-serving-gpu "*) ;; *) NAMES+=(model-serving-gpu);; esac
fi
ONLY=" ${NAMES[*]:-} "
want() { [ "$ONLY" = "  " ] || [[ "$ONLY" == *" $1 "* ]]; }
want_gpu() { [[ "$ONLY" == *" model-serving-gpu "* ]]; }   # 기본(전부) 빌드에는 들어가지 않는다
if want_gpu; then
  echo "== GPU 이미지(model-serving-gpu) 빌드 전 도커 디스크 사용량"
  "$DOCKER" system df || true
  echo "!! 이 빌드는 이미지 약 13GB(측정 전, model-runtime 안내값)를 추가한다. 도커 디스크 위치의 여유를 먼저 확인하라 (docs/RUN.md)."
  if [ $YES_LARGE = 1 ]; then :
  elif [ -t 0 ]; then printf '계속하려면 y: '; read -r ans; [ "$ans" = y ] || { echo "취소했다." >&2; exit 1; }
  else die "비대화형이다. 약 13GB 빌드를 진행하려면 --yes-large 를 명시하라"; fi
fi
SUFFIX=${BUILD_SUFFIX:-}
if [ "$ONLY" = "  " ]; then
  # 기본(전부) 빌드는 8개 기록을 새로 쓴다. 따로 빌드한 GPU 이미지 기록(model-serving-gpu)은 지우지 않는다(13GB를 다시 빌드하지 않게)
  # 단, 이미지가 실제로 있고 현재 기준 model-runtime 태그와 같은 커밋일 때만 유지한다(아니면 이유를 알리고 기록을 버린다: gpu_record_valid, lib.sh)
  GPU_KEEP=$(gpu_record_valid "$DEPLOY_ROOT/build/images.env" || true)
  rm -rf "$CTX" "$DEPLOY_ROOT/build/images.env"
  if [ -n "$GPU_KEEP" ]; then mkdir -p "$DEPLOY_ROOT/build"; printf '%s\n' "$GPU_KEEP" > "$DEPLOY_ROOT/build/images.env"; fi
fi
mkdir -p "$CTX"
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
# 경계 계약·turn-engine·model-runtime 태그(lib.sh 의 기준값, 2.0 구조). 각 영역 스크립트가 받는 환경 변수 이름이 달라 모두 같은 값으로 넘긴다
export BC="$DEPLOY_BC_TAG" MR="$DEPLOY_MR_TAG" TE="$DEPLOY_TE_TAG"   # 태그는 lib.sh 한 곳에서 정한다
for lib in boundary-contracts turn-engine model-runtime; do
  rm -rf "$CTX/$lib"; git clone -q --bare "$WORKSPACE/$lib" "$CTX/$lib"
done
declare -A SRC=( [survey-service]=survey-service [question-authoring]=question-authoring [ops-feedback]=ops-feedback [release-gate]=release-gate [model-registry]=model-lab [dataset-store]=synthetic-data [model-serving]=model-runtime [kiosk-frontend]=kiosk-frontend [admin-console]=admin-console )
# survey-service는 태그(survey-schema-v1.0.0)도 읽혀야 하므로 작업 트리가 있는 사본(clone, HEAD)으로 둔다
rm -rf "$CTX/survey-service"; git clone -q --no-hardlinks "$WORKSPACE/survey-service" "$CTX/survey-service"; rm -rf "$CTX/survey-service/.git/hooks"
for n in "${!SRC[@]}"; do
  want "$n" || continue
  [ "$n" = survey-service ] && continue
  [ "$n" = model-serving ] && continue
  rm -rf "$CTX/${SRC[$n]}"; mkdir -p "$CTX/${SRC[$n]}"; git -C "$WORKSPACE/${SRC[$n]}" archive HEAD | tar -x -C "$CTX/${SRC[$n]}"
done
touch "$DEPLOY_ROOT/build/images.env"
# 네 번째 열(의존 태그 도장)은 e2e.sh --reuse-build 가 이미지를 다시 써도 되는지 판정하는 데 쓴다(verify_area.py). 이미지 라벨은 영역마다 표기가 달라(v 접두, none, n/a) 비교에 쓸 수 없다
record() { sed -i "/^$1 /d" "$DEPLOY_ROOT/build/images.env"; echo "$1 $2 $3 bc=$BC,te=$TE,mr=$MR" >> "$DEPLOY_ROOT/build/images.env"; echo "빌드: $2"; }
commit_of() { echo "$(git -C "$WORKSPACE/$1" rev-parse --short HEAD)$SUFFIX"; }

if want survey-service; then
  ( cd "$CTX/survey-service" && BOUNDARY_TAG="$BC" MODEL_RUNTIME_TAG="$MR" TURN_ENGINE_TAG="$TE" PIP="$PIP" bash scripts/build_wheels.sh >/dev/null )
  set -a; source "$CTX/survey-service/build/wheels/VERSIONS.env"; set +a
  # io.openit.langgraph 라벨: 이미지에 설치되는 잠금 파일(requirements.lock)의 langgraph 버전
  LG=$(sed -n 's/^langgraph==\(.*\)$/\1/p' "$CTX/survey-service/requirements.lock" | head -1); [ -n "$LG" ] || { echo "requirements.lock 에서 langgraph 버전을 못 읽었다" >&2; exit 1; }
  c=$(commit_of survey-service); img="deploy-build/survey-service:$c"
  "$DOCKER" build -q -t "$img" --build-arg COMMIT="$c" --build-arg BOUNDARY_TAG="$BOUNDARY_TAG" \
    --build-arg SCHEMA_CONTRACT_VERSION="$SCHEMA_CONTRACT_VERSION" --build-arg TURN_ENGINE_TAG="$TURN_ENGINE_TAG" \
    --build-arg MODEL_RUNTIME_TAG="$MODEL_RUNTIME_TAG" --build-arg LANGGRAPH_VERSION="$LG" "$CTX/survey-service" >/dev/null
  record survey-service "$img" "$c"
fi
if want question-authoring; then
  ( cd "$CTX/question-authoring" && CONTRACTS_TAG="$BC" PYTHON="$PY" bash scripts/build_wheels.sh >/dev/null )
  c=$(commit_of question-authoring); img="deploy-build/question-authoring:$c"
  "$DOCKER" build -q -t "$img" --build-arg COMMIT="$c" --build-arg BOUNDARY_TAG="$(cat "$CTX/question-authoring/build/contracts.tag")" \
    --build-arg SURVEY_SCHEMA_TAG="$(cat "$CTX/question-authoring/build/survey-schema.tag")" "$CTX/question-authoring" >/dev/null
  record question-authoring "$img" "$c"
fi
if want ops-feedback; then
  ( cd "$CTX/ops-feedback" && BOUNDARY_TAG="$BC" PIP="$PIP" bash scripts/build_wheels.sh >/dev/null )
  c=$(commit_of ops-feedback); img="deploy-build/ops-feedback:$c"
  "$DOCKER" build -q -t "$img" --build-arg COMMIT="$c" --build-arg CONTRACTS_VERSION="$(cat "$CTX/ops-feedback/build/wheels/BOUNDARY_TAG")" \
    --build-arg SURVEY_SCHEMA_VERSION="$(cat "$CTX/ops-feedback/src/ops_feedback/_schemas/survey/v1/CONTRACT_VERSION")" "$CTX/ops-feedback" >/dev/null
  record ops-feedback "$img" "$c"
fi
if want release-gate; then
  # 영역의 build_image.sh 를 표준 `docker` 와 일반 경로로 부른다(turn-engine/model-runtime 는 형제 리포의 태그 시점 소스, 사본 기준).
  # 전제: release-gate 의 build_image.sh 가 docker.exe·wslpath 를 가정하지 않는 버전이다(CR-D21). 그 전 버전은 WSL 에서 UNC 경로를 만들어 실패한다.
  c=$(commit_of release-gate); img="deploy-build/release-gate:$c"
  ( cd "$CTX/release-gate" && DOCKER="$DOCKER" BOUNDARY_CONTRACTS_TAG="$BC" MODEL_RUNTIME_TAG="$MR" TURN_ENGINE_TAG="$TE" PYTHON="$PY" bash scripts/build_image.sh "$img" >/dev/null )
  record release-gate "$img" "$c"
fi
if want model-registry; then
  # Dockerfile은 boundary-contracts를 ssh로 받는다. 태그 시점 소스로 만든 wheel을 빌드 컨텍스트 wheels로 대신 준다(ssh 없이)
  ML="$CTX/model-lab"; BCTAG=$BC
  rm -rf "$ML/vendor-wheels" "$ML/bc-src"; mkdir -p "$ML/vendor-wheels" "$ML/bc-src"
  git -C "$CTX/boundary-contracts" archive "$BCTAG" | tar -x -C "$ML/bc-src"
  "$PIP" wheel -q --no-deps -w "$ML/vendor-wheels" "$ML/bc-src" >/dev/null 2>&1
  whl=$(basename "$(ls "$ML"/vendor-wheels/boundary_contracts-*.whl | head -1)")
  c=$(commit_of model-lab); img="deploy-build/model-registry:$c"
  "$DOCKER" build -q -t "$img" --build-context "wheels=$ML/vendor-wheels" --build-arg "BC_SPEC=/wheels/$whl" \
    --build-arg "BC_VERSION=$DEPLOY_BC_TAG" --build-arg "REVISION=$c" "$ML" >/dev/null
  record model-registry "$img" "$c"
fi

if want dataset-store; then
  # I2 DatasetStore HTTP 서버(계약 v2.1.0, D100, 소유 synthetic-data). 이미지는 boundary-contracts 를 ssh 로 받으므로 model-registry 와 같이 태그 시점 소스로 만든 wheel 을 빌드 컨텍스트 wheels 로 대신 준다.
  # 계약 태그는 기준 DEPLOY_BC_TAG(lib.sh). 문진 스키마는 이미지에 복사본을 두지 않고 빌드 컨텍스트 survey_schema 로 받는다(synthetic-data ADR 0011): survey-service 의 기준 스키마 태그 시점 schema/.
  DS="$CTX/synthetic-data"; DSW="$CTX/ds-wheels"; DSB="$CTX/ds-bc-src"; DSS="$CTX/ds-schema"
  rm -rf "$DS" "$DSW" "$DSB" "$DSS"; mkdir -p "$DS" "$DSW" "$DSB" "$DSS"; git -C "$WORKSPACE/synthetic-data" archive HEAD | tar -x -C "$DS"
  git -C "$CTX/boundary-contracts" archive "$DEPLOY_BC_TAG" | tar -x -C "$DSB"
  "$PIP" wheel -q --no-deps -w "$DSW" "$DSB" >/dev/null 2>&1
  whl=$(basename "$(ls "$DSW"/boundary_contracts-*.whl | head -1)")
  git -C "$CTX/survey-service" archive "$DEPLOY_SS_TAG" schema | tar -x -C "$DSS"
  c=$(commit_of synthetic-data); img="deploy-build/dataset-store:$c"
  "$DOCKER" build -q -t "$img" --build-context "wheels=$DSW" --build-context "survey_schema=$DSS/schema" --build-arg "BC_SPEC=/wheels/$whl" \
    --build-arg "BC_VERSION=$DEPLOY_BC_TAG" --build-arg "REVISION=$c" "$DS" >/dev/null
  record dataset-store "$img" "$c"
fi

# 호스트에서 쓰는 wheel: E2E 클라이언트·검증기와 synthetic-data 잡용(같은 기준 태그)
mkdir -p "$DEPLOY_ROOT/build/hostwheels"; rm -f "$DEPLOY_ROOT/build/hostwheels"/*.whl
for tag in "$BC"; do
  d="$DEPLOY_ROOT/build/hostsrc-$tag"; rm -rf "$d"; mkdir -p "$d"; git -C "$CTX/boundary-contracts" archive "$tag" | tar -x -C "$d"
  mkdir -p "$DEPLOY_ROOT/build/hostwheels/$tag"; "$PIP" wheel -q --no-deps -w "$DEPLOY_ROOT/build/hostwheels/$tag" "$d" >/dev/null 2>&1
done

if want model-serving; then
  # 추론 서버(model-runtime, CPU/fake 변형). 같은 Dockerfile의 변형은 VARIANT 인자(기본 cpu, gpu는 GPU 서버 전용·13GB라 E2E 제외).
  # boundary-contracts 폴더는 태그 시점 소스를 빌드 컨텍스트 boundary 로 준다(CI는 태그 설치로 바꾼다).
  MS="$CTX/model-serving"; rm -rf "$MS" "$CTX/bc-folder"; mkdir -p "$MS" "$CTX/bc-folder"
  git -C "$WORKSPACE/model-runtime" archive "$MR" | tar -x -C "$MS"   # 추론 서버는 model-runtime 태그 시점 소스
  git -C "$CTX/boundary-contracts" archive "$BC" | tar -x -C "$CTX/bc-folder"
  # 문진 스키마를 이미지에 내장한다(D72): survey-service 태그 시점의 schema/ 를 빌드 컨텍스트 schema 로 준다 -> /opt/survey-schema.
  # 추론 서버가 스키마 마운트·일회성 추출 서비스 없이 이미지 하나로 뜬다(다른 호스트에서도 같다).
  rm -rf "$CTX/ms-schema"; mkdir -p "$CTX/ms-schema"
  git -C "$CTX/survey-service" archive "$DEPLOY_SS_TAG" schema | tar -x -C "$CTX/ms-schema"
  c=$(git -C "$WORKSPACE/model-runtime" rev-parse --short "$MR^{commit}")$SUFFIX; img="deploy-build/model-serving:$c"
  "$DOCKER" build -q -t "$img" --build-context "boundary=$CTX/bc-folder" --build-context "schema=$CTX/ms-schema/schema" --build-arg REVISION="$c" --build-arg BOUNDARY_VERSION="$BC" \
    --build-arg SURVEY_SCHEMA_VERSION=1 --build-arg TURN_ENGINE_VERSION="$DEPLOY_TE_TAG" "$MS" >/dev/null
  record model-serving "$img" "$c"
fi

if want kiosk-frontend; then
  # 키오스크 앱+직원 콘솔 정적 이미지(태그 없음 = main). 빌드 컨텍스트는 git archive 사본
  KF="$CTX/kiosk-frontend"; AV=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$KF/package.json" | head -1)
  c=$(commit_of kiosk-frontend); img="deploy-build/kiosk-frontend:$c"
  "$DOCKER" build -q -t "$img" --build-arg REVISION="$c" --build-arg BOUNDARY_CONTRACT="$BC" --build-arg SURVEY_SCHEMA=1 --build-arg APP_VERSION="${AV:-unknown}" "$KF" >/dev/null
  record kiosk-frontend "$img" "$c"
fi

if want admin-console; then
  # 출고 승인 화면 정적 이미지(태그 없음 = 로컬 폴더). /v1 은 프록시하지 않는다. ADMIN_DEV_APPROVER_ID 는 설정하지 않는다
  c=$(commit_of admin-console); img="deploy-build/admin-console:$c"
  "$DOCKER" build -q -t "$img" --build-arg REVISION="$c" --build-arg BOUNDARY_CONTRACTS="$BC" --build-arg SURVEY_SCHEMA=n/a "$CTX/admin-console" >/dev/null
  record admin-console "$img" "$c"
fi

if want_gpu; then
  # 추론 서버 GPU 변형(D72/D73): 같은 Dockerfile 의 VARIANT=gpu. 문진 스키마 내장. 프로파일은 이미지 안 /app/profiles/ (model-runtime $DEPLOY_MR_TAG).
  MSG="$CTX/model-serving-gpu"; rm -rf "$MSG" "$CTX/bc-folder-gpu" "$CTX/ms-schema-gpu"; mkdir -p "$MSG" "$CTX/bc-folder-gpu" "$CTX/ms-schema-gpu"
  git -C "$WORKSPACE/model-runtime" archive "$DEPLOY_MR_TAG" | tar -x -C "$MSG"
  git -C "$CTX/boundary-contracts" archive "$BC" | tar -x -C "$CTX/bc-folder-gpu"
  git -C "$CTX/survey-service" archive "$DEPLOY_SS_TAG" schema | tar -x -C "$CTX/ms-schema-gpu"
  c=$(git -C "$WORKSPACE/model-runtime" rev-parse --short "$DEPLOY_MR_TAG^{commit}")$SUFFIX; img="deploy-build/model-serving-gpu:$c"
  echo "== model-serving-gpu 빌드 (VARIANT=gpu, model-runtime $DEPLOY_MR_TAG)"
  "$DOCKER" build -q -t "$img" --build-arg VARIANT=gpu --label io.openit.variant=gpu \
    --build-context "boundary=$CTX/bc-folder-gpu" --build-context "schema=$CTX/ms-schema-gpu/schema" --build-arg REVISION="$c" --build-arg BOUNDARY_VERSION="$BC" \
    --build-arg SURVEY_SCHEMA_VERSION=1 --build-arg TURN_ENGINE_VERSION="$DEPLOY_TE_TAG" "$MSG" >/dev/null
  record model-serving-gpu "$img" "$c"
  echo "== GPU 이미지 빌드 후 도커 디스크 사용량"; "$DOCKER" system df || true
  OLD=$("$DOCKER" image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' "deploy-build/model-serving-gpu" 2>/dev/null | grep -v "^$img " || true)
  if [ -n "$OLD" ]; then
    echo "!! 이전 GPU 이미지가 태그를 가진 채 남아 있다(커밋이 다르면 태그도 다르다). 디스크 회수는 사용자가 판단해 지운다:"
    printf '%s\n' "$OLD" | sed 's/^/     docker rmi /'
  fi
fi
