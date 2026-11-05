#!/usr/bin/env bash
# 호스트에서 쓰는 wheel을 기준표 태그에서 만든다: build/hostwheels/<계약 태그>/boundary_contracts-*.whl 과 build/hostwheels/survey-schema/*.whl.
# 쓰는 곳: prepare-host.sh wheels(deploy venv 설치), build-tool-image.sh(도구 이미지), E2E 클라이언트·검증기, synthetic-data 잡. 만드는 곳은 여기 한 곳이다(build-images.sh 와 e2e.sh 가 부른다):
# 같은 실행 안에서 만들고 쓴다 -- 이전 실행이 남긴 폴더에 기대지 않는다(깨끗한 환경에서도 도구 이미지 빌드가 서야 한다).
# 소스는 영역 리포가 아니라 기준표 태그의 git archive 다(계약 리포의 태그, 문진 스키마 태그). 빌드 도구는 deploy .venv 의 pip(wheel 만들기만, 설치하지 않는다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
BC="$DEPLOY_BC_TAG"; PIP="$VENV/bin/pip"
H="$DEPLOY_ROOT/build/hostwheels"; SRC="$DEPLOY_ROOT/build/hostsrc-$BC"
mkdir -p "$H"; rm -f "$H"/*.whl
rm -rf "$SRC" "$DEPLOY_ROOT/build/hostsrc-survey-schema"; mkdir -p "$SRC" "$DEPLOY_ROOT/build/hostsrc-survey-schema" "$H/$BC" "$H/survey-schema"
git -C "$WORKSPACE/boundary-contracts" archive "$BC" | tar -x -C "$SRC"
git -C "$WORKSPACE/survey-service" archive "$DEPLOY_SS_TAG" schema | tar -x -C "$DEPLOY_ROOT/build/hostsrc-survey-schema"
"$PIP" wheel -q --no-deps --no-build-isolation -w "$H/$BC" "$SRC" >/dev/null 2>&1 || die "계약 $BC 의 호스트 wheel 을 만들지 못했다"
"$PIP" wheel -q --no-deps --no-build-isolation -w "$H/survey-schema" "$DEPLOY_ROOT/build/hostsrc-survey-schema/schema" >/dev/null 2>&1 || die "문진 스키마 $DEPLOY_SS_TAG 의 호스트 wheel 을 만들지 못했다"
ls "$H/$BC"/boundary_contracts-*.whl >/dev/null || die "계약 wheel 이 없다"
echo "호스트 wheel: $H/$BC, $H/survey-schema"
