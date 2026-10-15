#!/usr/bin/env bash
# 네 영역 이미지를 로컬에서 빌드한다(D22). 이웃 리포지토리는 수정하지 않는다:
#  - 영역 리포지토리는 `git archive HEAD`로 build/ctx/<이름>/ 에 꺼내 거기서 빌드한다.
#  - 라이브러리(boundary-contracts, turn-engine, model-runtime)는 영역들의 빌드 스크립트가 `git -C ../<이름> archive <태그>`로
#    읽으므로 build/ctx/<이름>/ 에 bare 사본을 둔다(태그 시점 소스만 쓰인다).
# 결과: build/images.env (로컬 이미지 이름, 커밋). 레지스트리에 올리고 digest 잠금을 만드는 일은 publish-images.sh.
# 사용: build-images.sh [영역 ...]   (비우면 네 영역 전부)
#  BUILD_SUFFIX: 시험 전용. 이미지 COMMIT 라벨 뒤에 붙여 다른 digest를 만든다(롤백 시험이 "새 버전"으로 쓴다). 운영에는 쓰지 않는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CTX="$DEPLOY_ROOT/build/ctx"
ONLY=" $* "
want() { [ "$ONLY" = "  " ] || [[ "$ONLY" == *" $1 "* ]]; }
SUFFIX=${BUILD_SUFFIX:-}
if [ "$ONLY" = "  " ]; then rm -rf "$CTX" "$DEPLOY_ROOT/build/images.env"; fi
mkdir -p "$CTX"
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
for lib in boundary-contracts turn-engine model-runtime; do
  [ -d "$CTX/$lib" ] || git clone -q --bare "$WORKSPACE/$lib" "$CTX/$lib"
done
for a in $SERVICES; do
  want "$a" || continue
  rm -rf "$CTX/$a"; mkdir -p "$CTX/$a"; git -C "$WORKSPACE/$a" archive HEAD | tar -x -C "$CTX/$a"
done
[ -d "$CTX/survey-service/schema" ] || { mkdir -p "$CTX/survey-service"; git -C "$WORKSPACE/survey-service" archive HEAD schema | tar -x -C "$CTX/survey-service"; }
touch "$DEPLOY_ROOT/build/images.env"
build() { # build <영역> <build-arg...>
  local a=$1; shift
  local commit; commit=$(git -C "$WORKSPACE/$a" rev-parse --short HEAD)$SUFFIX
  local img="deploy-build/$a:$commit"
  "$DOCKER" build -q -t "$img" --build-arg COMMIT="$commit" "$@" "$(hostpath "$CTX/$a")" >/dev/null
  sed -i "/^$a /d" "$DEPLOY_ROOT/build/images.env"; echo "$a $img $commit" >> "$DEPLOY_ROOT/build/images.env"
  echo "빌드: $img"
}
# survey-service
if want survey-service; then
( cd "$CTX/survey-service" && PIP="$PIP" bash scripts/build_wheels.sh >/dev/null )
set -a; source "$CTX/survey-service/build/wheels/VERSIONS.env"; set +a
build survey-service --build-arg BOUNDARY_TAG="$BOUNDARY_TAG" --build-arg SCHEMA_CONTRACT_VERSION="$SCHEMA_CONTRACT_VERSION" \
  --build-arg TURN_ENGINE_TAG="$TURN_ENGINE_TAG" --build-arg MODEL_RUNTIME_TAG="$MODEL_RUNTIME_TAG"
fi
# question-authoring (Dockerfile이 build/survey-schema를 기대하지만 스크립트가 만들지 않는다: change-requests/CR-D03)
if want question-authoring; then
( cd "$CTX/question-authoring" && PYTHON="$PY" bash scripts/build_contract_wheel.sh )
mkdir -p "$CTX/question-authoring/build/survey-schema"
cp -r "$CTX/survey-service/schema/CONTRACT_VERSION" "$CTX/survey-service/schema/schemas" "$CTX/question-authoring/build/survey-schema/"
build question-authoring --build-arg CONTRACT_VERSION="$(cat "$CTX/survey-service/schema/CONTRACT_VERSION")" \
  --build-arg BOUNDARY_CONTRACTS_REV="$(cat "$CTX/question-authoring/build/contracts.rev")"
fi
# ops-feedback
if want ops-feedback; then
( cd "$CTX/ops-feedback" && PIP="$PIP" bash scripts/build_wheels.sh >/dev/null )
build ops-feedback --build-arg CONTRACTS_VERSION="$(cat "$CTX/ops-feedback/build/wheels/BOUNDARY_TAG")"
fi
if want release-gate; then
# release-gate (stage_context.sh가 .build/ctx를 만든다. 컨텍스트는 그 안이다)
( cd "$CTX/release-gate" && PYTHON="$PY" bash scripts/stage_context.sh >/dev/null 2>&1 )
RG="$CTX/release-gate/.build/ctx"
rgcommit=$(git -C "$WORKSPACE/release-gate" rev-parse --short HEAD)$SUFFIX
pver=$(sed -n 's/^PIPELINE_SCHEMA_VERSION = "\(.*\)"/\1/p' "$CTX/release-gate/release_gate/__init__.py")
"$DOCKER" build -q -t "deploy-build/release-gate:$rgcommit" -f "$(hostpath "$CTX/release-gate/Dockerfile")" \
  --build-arg COMMIT="$rgcommit" --build-arg CONTRACT_VERSION="$(cat "$RG/survey-schema/CONTRACT_VERSION")" \
  --build-arg PIPELINE_SCHEMA_VERSION="$pver" "$(hostpath "$RG")" >/dev/null
sed -i "/^release-gate /d" "$DEPLOY_ROOT/build/images.env"; echo "release-gate deploy-build/release-gate:$rgcommit $rgcommit" >> "$DEPLOY_ROOT/build/images.env"
echo "빌드: deploy-build/release-gate:$rgcommit"
fi
