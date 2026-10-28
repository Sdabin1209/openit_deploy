#!/usr/bin/env bash
# 버전 표 드리프트 점검. 기준은 scripts/lib.sh 의 표(DEPLOY_BC_TAG, DEPLOY_MR_TAG) 하나다.
# 형제 영역의 requirements*/lock/pyproject/Dockerfile/스크립트가 적은 boundary-contracts·model-runtime 태그를 읽기 전용으로 모아
# 표와 다르면 실패하고 파일:줄을 출력한다. 문서(*.md)와 시험·변경 이력은 보지 않는다(과거 기록이라 다를 수 있다).
# 대상 영역: head/shared/areas.json 의 version_train 영역(kiosk-frontend·admin-console 의 Dockerfile ARG BOUNDARY_CONTRACT[S]=vX 포함).
# 사용: check-versions.sh        환경: CHECK_VERSIONS_WORKSPACE(시험용: 형제 폴더가 있는 곳, 기본 워크스페이스)
#   표를 덮어쓰는 환경 변수(BOUNDARY_TAG_ALL, MODEL_RUNTIME_TAG_ALL)는 무시하고 lib.sh 의 기본 표를 기준으로 삼는다.
set -uo pipefail
export DEPLOY_NO_DOCKER=1
unset BOUNDARY_TAG_ALL MODEL_RUNTIME_TAG_ALL
source "$(dirname "$0")/lib.sh"
WS="${CHECK_VERSIONS_WORKSPACE:-$WORKSPACE}"
VERSION_REPOS="$(AREAS_FILE="$WS/head/shared/areas.json" areas_list --train)" || exit 1; export VERSION_REPOS   # 정본: head/shared/areas.json
export WS EXP_BC="$DEPLOY_BC_TAG" EXP_MR="$DEPLOY_MR_TAG"
exec python3 -I "$(dirname "$0")/check_versions.py"
