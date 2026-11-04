#!/usr/bin/env bash
# 인증 없는 요청에 공개 입구가 주는 응답을 점검한다: 기대 행의 정본은 platform 공개 입구 이미지의 selfcheck-unauth 명령이다(손 표 없음, platform docs/boundary.md).
# 왜 deploy 가 표를 두지 않나: 기대 행은 영역 Exposure 선언에서 만들어지는 이미지의 지식이다(구조 규칙 1·6). deploy 는 띄운 스택에 실행만 한다.
# 사용: check-unauth.sh <프로젝트> <https://공개 입구가 받는 이름:포트> <루트 인증서 파일>   (종료 코드는 selfcheck-unauth 의 것: 0 일치, 1 어긋남, 2 입력 오류)
# 인증서 검증은 끄지 않는다(--insecure 폐지, --cacert 필수). 선언 폴더는 공개 입구를 띄울 때 마운트한 것과 같다($GATEWAYS_DIR/exposures).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
PROJECT=${1:?사용: check-unauth.sh <프로젝트> <https://이름:포트> <루트 인증서 파일>}; URL=${2:?}; CA=${3:?}
set -a; . "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; . "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"; set +a
IMG="${DEPLOY_REGISTRY:?}/openit/public-ingress@${PUBLIC_INGRESS_DIGEST:?locks/images.lock}"
detect_docker
exec "$DOCKER" run --rm --network "${PROJECT}_edge" -v "${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}/exposures:/etc/openit/exposures:ro" -v "$CA:/ca.crt:ro" \
  --entrypoint selfcheck-unauth "$IMG" "$URL" --cacert /ca.crt
