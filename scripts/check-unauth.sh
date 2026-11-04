#!/usr/bin/env bash
# 인증 없는 요청에 공개 입구가 주는 응답을 점검한다. 같은 망의 클라이언트 컨테이너(UTIL 이미지)가 https://<공개 입구가 받는 이름> 으로 인증 없는 요청을 보내고, 기대 응답은 계약(영역 Exposure 선언의 auth, RUNTIME R3.13·R3.23, CONVENTIONS 9절)에서 만든다
# (scripts/check_unauth.py). 공개 입구 이미지의 점검 명령에 기대지 않는다(deploy 는 그 이미지의 내부 명령을 모른다, 구조 규칙 1·6). 선언 폴더는 공개 입구를 띄울 때 마운트한 것과 같다($GATEWAYS_DIR/exposures).
# 사용: check-unauth.sh <프로젝트> <https://이름:포트> <루트 인증서 파일>   종료 코드: 0 일치, 1 어긋남, 2 입력 오류. 인증서 검증을 끄지 않는다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
PROJECT=${1:?사용: check-unauth.sh <프로젝트> <https://이름:포트> <루트 인증서 파일>}; URL=${2:?}; CA=${3:?}
set -a; . "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; set +a
detect_docker
exec "$DOCKER" run --rm --network "${PROJECT}_edge" -v "${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}/exposures:/exposures:ro" -v "$CA:/ca.crt:ro" -v "$DEPLOY_ROOT/scripts/check_unauth.py:/check_unauth.py:ro" \
  "${UTIL_IMAGE:?locks/images.lock}" python /check_unauth.py "$URL" --exposures /exposures --cacert /ca.crt
