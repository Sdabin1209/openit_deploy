#!/usr/bin/env bash
# 다섯 서비스 이미지를 로컬에서 빌드한다(D22). 이웃 리포지토리는 수정하지 않는다:
#  - 영역 리포지토리는 `git archive HEAD`로 build/ctx/<이름>/ 에 꺼내 거기서 빌드한다.
#  - 라이브러리(boundary-contracts, turn-engine, model-runtime)는 영역들의 빌드 스크립트가 `git -C ../<이름> archive <태그>`로
#    읽으므로 build/ctx/<이름>/ 에 bare 사본을 둔다(태그 시점 소스만 쓰인다). 태그는 각 영역 스크립트의 기본값을 따른다.
# 이미지 이름: survey-service question-authoring ops-feedback release-gate model-registry(소스는 model-lab 리포지토리)
# 결과: build/images.env (영역 로컬이름 커밋). 레지스트리에 올리고 digest 잠금을 만드는 일은 publish-images.sh.
# 사용: build-images.sh [이름 ...]   (비우면 전부)
#  BUILD_SUFFIX: 시험 전용. COMMIT 라벨 뒤에 붙여 다른 digest를 만든다(롤백 시험). 운영에는 쓰지 않는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CTX="$DEPLOY_ROOT/build/ctx"
ONLY=" $* "
want() { [ "$ONLY" = "  " ] || [[ "$ONLY" == *" $1 "* ]]; }
SUFFIX=${BUILD_SUFFIX:-}
if [ "$ONLY" = "  " ]; then rm -rf "$CTX" "$DEPLOY_ROOT/build/images.env"; fi
mkdir -p "$CTX"
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
# 경계 계약 태그(D53 이후 v1.3.1). 각 영역 스크립트가 받는 환경 변수 이름이 달라 모두 같은 값으로 넘긴다
export BC="$DEPLOY_BC_TAG" MR="$DEPLOY_MR_TAG"   # 태그는 lib.sh 한 곳에서 정한다
for lib in boundary-contracts turn-engine model-runtime; do
  rm -rf "$CTX/$lib"; git clone -q --bare "$WORKSPACE/$lib" "$CTX/$lib"
done
declare -A SRC=( [survey-service]=survey-service [question-authoring]=question-authoring [ops-feedback]=ops-feedback [release-gate]=release-gate [model-registry]=model-lab [model-serving]=model-runtime [kiosk-frontend]=kiosk-frontend [admin-console]=admin-console )
# survey-service는 태그(survey-schema-v1.0.0)도 읽혀야 하므로 작업 트리가 있는 사본(clone, HEAD)으로 둔다
rm -rf "$CTX/survey-service"; git clone -q --no-hardlinks "$WORKSPACE/survey-service" "$CTX/survey-service"; rm -rf "$CTX/survey-service/.git/hooks"
for n in "${!SRC[@]}"; do
  want "$n" || continue
  [ "$n" = survey-service ] && continue
  [ "$n" = model-serving ] && continue
  rm -rf "$CTX/${SRC[$n]}"; mkdir -p "$CTX/${SRC[$n]}"; git -C "$WORKSPACE/${SRC[$n]}" archive HEAD | tar -x -C "$CTX/${SRC[$n]}"
done
touch "$DEPLOY_ROOT/build/images.env"
record() { sed -i "/^$1 /d" "$DEPLOY_ROOT/build/images.env"; echo "$1 $2 $3" >> "$DEPLOY_ROOT/build/images.env"; echo "빌드: $2"; }
commit_of() { echo "$(git -C "$WORKSPACE/$1" rev-parse --short HEAD)$SUFFIX"; }

if want survey-service; then
  ( cd "$CTX/survey-service" && BOUNDARY_TAG="$BC" MODEL_RUNTIME_TAG="$MR" PIP="$PIP" bash scripts/build_wheels.sh >/dev/null )
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
  ( cd "$CTX/release-gate" && DOCKER="$DOCKER" BOUNDARY_CONTRACTS_TAG="$BC" MODEL_RUNTIME_TAG="$MR" PYTHON="$PY" bash scripts/build_image.sh "$img" >/dev/null )
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
    --build-arg "REVISION=$c" "$ML" >/dev/null
  record model-registry "$img" "$c"
fi

# 호스트에서 쓰는 wheel: E2E 클라이언트·검증기(v1.3.1)와 synthetic-data용(그 영역이 고정한 태그 v1.2.0)
mkdir -p "$DEPLOY_ROOT/build/hostwheels"; rm -f "$DEPLOY_ROOT/build/hostwheels"/*.whl
for tag in "$BC" "$DEPLOY_BC_TAG_SD"; do
  d="$DEPLOY_ROOT/build/hostsrc-$tag"; rm -rf "$d"; mkdir -p "$d"; git -C "$CTX/boundary-contracts" archive "$tag" | tar -x -C "$d"
  mkdir -p "$DEPLOY_ROOT/build/hostwheels/$tag"; "$PIP" wheel -q --no-deps -w "$DEPLOY_ROOT/build/hostwheels/$tag" "$d" >/dev/null 2>&1
done

if want model-serving; then
  # 추론 서버(model-runtime, CPU/fake 변형). 같은 Dockerfile의 변형은 VARIANT 인자(기본 cpu, gpu는 GPU 서버 전용·13GB라 E2E 제외).
  # boundary-contracts 폴더는 태그 시점 소스를 빌드 컨텍스트 boundary 로 준다(CI는 태그 설치로 바꾼다).
  MS="$CTX/model-serving"; rm -rf "$MS" "$CTX/bc-folder"; mkdir -p "$MS" "$CTX/bc-folder"
  git -C "$WORKSPACE/model-runtime" archive "$MR" | tar -x -C "$MS"   # 추론 서버는 model-runtime 태그 시점 소스
  git -C "$CTX/boundary-contracts" archive "$BC" | tar -x -C "$CTX/bc-folder"
  c=$(git -C "$WORKSPACE/model-runtime" rev-parse --short "$MR^{commit}")$SUFFIX; img="deploy-build/model-serving:$c"
  "$DOCKER" build -q -t "$img" --build-context "boundary=$CTX/bc-folder" --build-arg REVISION="$c" --build-arg BOUNDARY_VERSION="$BC" \
    --build-arg SURVEY_SCHEMA_VERSION=1 --build-arg TURN_ENGINE_VERSION=v0.2.0 "$MS" >/dev/null
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
