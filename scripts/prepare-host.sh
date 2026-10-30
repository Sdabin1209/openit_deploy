#!/usr/bin/env bash
# 호스트에서 쓰는 가상환경·클라이언트 준비(e2e.sh 와 demo.sh 가 같이 쓴다). Docker 가 필요 없다.
#  venv   : .venv 가상환경과 requirements.txt (build-images.sh 가 wheel 을 만들 때 쓴다 -> 이미지 빌드 전에)
#  wheels : 이미지 빌드가 만든 태그 wheel(boundary-contracts, 문진 스키마)을 .venv 에 설치하고, synthetic-data 용 가상환경과 소스를 준비 (이미지 빌드 후에)
set -euo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
case "${1:-}" in
  venv)
    [ -d "$DEPLOY_ROOT/.venv" ] || python3 -m venv "$DEPLOY_ROOT/.venv"
    "$VENV/bin/pip" install -q -r "$DEPLOY_ROOT/requirements.txt" setuptools wheel 2>&1 | tail -1
    # 통신 기반 라이브러리 link 는 Git 태그로 설치한다(D118, 공통 규칙 "라이브러리는 Git 태그로 설치"). 기본은 GitHub 리포(openit_link). LINK_SOURCE 로 다른 위치(예: 로컬 리포 git+file:///.../link)를 가리킬 수 있다. 계약(boundary-contracts)은 wheels 단계가 설치하므로 --no-deps
    "$VENV/bin/pip" install -q --no-deps "${LINK_SOURCE:-git+ssh://git@github.com/Sdabin1209/openit_link.git}@$DEPLOY_LINK_TAG" 2>&1 | tail -1
    # model-runtime 은 check-all 이 공개 이름(model_runtime.prompts.SUPPORTED_TEMPLATE_VERSIONS)을 읽으려고 기준 태그로 설치한다(구조 규칙 1: 이웃 소스 파일을 열지 않는다). 의존 패키지는 설치하지 않는다(--no-deps: 읽는 모듈은 prompts 뿐). 다른 위치는 MODEL_RUNTIME_SOURCE (예: git+file:///.../model-runtime)
    "$VENV/bin/pip" install -q --no-deps "${MODEL_RUNTIME_SOURCE:-git+ssh://git@github.com/Sdabin1209/openit_model-runtime.git}@$DEPLOY_MR_TAG" 2>&1 | tail -1 ;;
  wheels)
    # 호스트에서 쓰는 검증기·클라이언트: 영역 빌드가 만든 태그 wheel(boundary-contracts)과 survey-service HEAD 의 문진 스키마(v2 구조의 FrontendInput·TurnTrace 검증용)
    "$VENV/bin/pip" install -q --force-reinstall --no-deps "$DEPLOY_ROOT"/build/hostwheels/"$DEPLOY_BC_TAG"/boundary_contracts-*.whl "$DEPLOY_ROOT"/build/hostwheels/survey-schema/openit_survey_schema-*.whl 2>&1 | tail -1 ;;
  *) echo "사용: prepare-host.sh venv|wheels" >&2; exit 2 ;;
esac
