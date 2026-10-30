#!/usr/bin/env bash
# link 핀 대조 한 번(U59, ADR 0046): 영역 main 잠금 파일의 openit-link 태그 == lib.sh 의 DEPLOY_LINK_TAG. e2e.sh 시작 점검이 부른다. 종료 코드: 0 같다, 1 어긋남, 3 검증하지 못함(check_link_pins.py).
# 환경(시험용): LINK_PINS_WS (영역 리포가 있는 폴더, 기본 deploy 의 상위), LINK_PINS_TAG (기준 태그를 덮어쓴다). 파이썬은 lib.sh 의 DEPLOY_PY(스키마 검증에 jsonschema 가 필요하다).
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
args=(); [ -z "${LINK_PINS_WS:-}" ] || args+=(--ws "$LINK_PINS_WS"); [ -z "${LINK_PINS_TAG:-}" ] || args+=(--tag "$LINK_PINS_TAG")
exec "$DEPLOY_PY" -W ignore "$DEPLOY_ROOT/scripts/check_link_pins.py" "${args[@]}"
