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
    "$VENV/bin/pip" install -q -r "$DEPLOY_ROOT/requirements.txt" setuptools wheel 2>&1 | tail -1 ;;
  wheels)
    # 호스트에서 쓰는 검증기·클라이언트: 영역 빌드가 만든 태그 wheel(boundary-contracts, 문진 스키마)
    "$VENV/bin/pip" install -q --force-reinstall --no-deps "$DEPLOY_ROOT"/build/hostwheels/"$DEPLOY_BC_TAG"/boundary_contracts-*.whl "$DEPLOY_ROOT"/build/ctx/question-authoring/build/wheels/openit_survey_schema-*.whl 2>&1 | tail -1
    # synthetic-data run-once용 가상환경(호스트): 그 영역 런북대로 requirements.lock 의 서드파티 + 태그 wheel
    if [ ! -x "$DEPLOY_ROOT/build/venv-sd/bin/python" ]; then python3 -m venv "$DEPLOY_ROOT/build/venv-sd"; "$DEPLOY_ROOT/build/venv-sd/bin/pip" install -q attrs==26.1.0 jsonschema==4.10.3 packaging==26.3 pyrsistent==0.20.0 PyYAML==6.0.3 2>&1 | tail -1; fi
    "$DEPLOY_ROOT/build/venv-sd/bin/pip" install -q --force-reinstall --no-deps "$DEPLOY_ROOT"/build/hostwheels/"$DEPLOY_BC_TAG_SD"/boundary_contracts-*.whl 2>&1 | tail -1
    rm -rf "$DEPLOY_ROOT/build/ctx/synthetic-data"; mkdir -p "$DEPLOY_ROOT/build/ctx/synthetic-data"; git -C "$WORKSPACE/synthetic-data" archive HEAD | tar -x -C "$DEPLOY_ROOT/build/ctx/synthetic-data" ;;
  *) echo "사용: prepare-host.sh venv|wheels" >&2; exit 2 ;;
esac
