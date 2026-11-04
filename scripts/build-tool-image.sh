#!/usr/bin/env bash
# deploy 도구 이미지를 만든다: E2E 시험 드라이버가 영역 게이트웨이를 외부 호출자처럼 부르는 같은 망 클라이언트 컨테이너의 이미지(scripts/e2e_sandbox.py exec_py).
# 사용: build-tool-image.sh   (끝줄에 이미지 이름을 낸다)
# 왜 영역 이미지를 안 쓰나: deploy 는 영역 이미지 안의 명령·파일을 모른다(구조 규칙 1). 이 이미지는 deploy 소유 도구다(UTIL 이미지와 같은 종류): 기준표의 link 태그(DEPLOY_LINK_TAG)와 계약 태그(DEPLOY_BC_TAG)의 클라이언트만 담는다.
# 이름·태그에 두 태그와 deploy 커밋을 넣는다(같은 입력이면 같은 이름, 다르면 다른 이름). 라벨 io.openit.service=deploy-tool, io.openit.owner=deploy 로 영역 이미지와 구분한다.
# 한계: 의존 패키지(jsonschema 등)는 이미지 빌드 중 pip 가 받는다(네트워크 필요). link 는 Git 태그(원격 동결 중에는 로컬 미러, git_mirror_env)로 받는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
detect_docker
git_mirror_env || die "로컬 미러 git 설정을 만들지 못했다 (scripts/write-local-mirrors.sh)"
rev=$(git -C "$DEPLOY_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
TAG="deploy-build/deploy-tool:${rev}-bc${DEPLOY_BC_TAG#v}-link${DEPLOY_LINK_TAG#v}"
if "$DOCKER" image inspect "$TAG" >/dev/null 2>&1; then echo "$TAG"; exit 0; fi
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"); [ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금에 없다"
CTX="$DEPLOY_ROOT/build/tool-image"; rm -rf "$CTX"; mkdir -p "$CTX/wheels"
bcw=$(ls "$DEPLOY_ROOT/build/hostwheels/$DEPLOY_BC_TAG"/boundary_contracts-*.whl 2>/dev/null | head -1) || true
[ -n "${bcw:-}" ] || die "계약 $DEPLOY_BC_TAG 의 호스트 wheel 이 없다: bash scripts/build-images.sh 가 만든다(또는 prepare-host.sh wheels 의 전제)"
cp "$bcw" "$CTX/wheels/"
"$VENV/bin/pip" wheel -q --no-deps -w "$CTX/wheels" "${LINK_SOURCE:-git+ssh://git@github.com/Sdabin1209/openit_link.git}@$DEPLOY_LINK_TAG" >/dev/null 2>&1 || die "link $DEPLOY_LINK_TAG 의 wheel 을 만들지 못했다"
cat > "$CTX/Dockerfile" <<DOCKER
FROM ${UTIL}
COPY wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels  # own-venv: 이미지 안의 pip, deploy venv 가 아니다
USER 10001:10001
LABEL io.openit.service=deploy-tool io.openit.owner=deploy io.openit.revision=${rev} io.openit.contracts.boundary=${DEPLOY_BC_TAG} io.openit.link=${DEPLOY_LINK_TAG}
DOCKER
"$DOCKER" build -q --provenance=false -t "$TAG" "$CTX" >/dev/null || die "deploy 도구 이미지를 빌드하지 못했다"
echo "$TAG"
