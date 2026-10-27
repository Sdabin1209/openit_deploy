#!/usr/bin/env bash
# 영역을 가로지르는 정적 일관성 점검. 실행 없이 읽어서 아는 영역 사이 어긋남을 E2E(6분) 앞에서 잡는다(수 초~1분).
# 규칙: 0 대상 열거(모르는 대상), 1 버전표, 2 예시 키 순서, 3 완화 정책, 4 삭제된 이름, 5 박힌 계약 문자열, 6 설정 인라인 비밀,
#       7 compose 비밀, 8 시험 수집, 9 README 절, 10 E2E 통과 수는 정본(deploy/docs/E2E_RESULTS.md)에만. 규칙 2 대상: scripts/check-all-ordered-schemas.txt. 규칙 9의 필수 절 7개 정의: check_all.py 의 README_SECTIONS 주석. 규칙 10 판정: scripts/check-all-e2e-claims.txt.
# 출력: 규칙마다 'PASS|FAIL|SKIP' 과 '검증됨 N/M, 어긋남, 대상 아님(이유), 검증 안 함(이유)'. FAIL 은 영역/파일:줄 근거.
#   검증 대상에서 빠진 것을 통과로 세지 않는다. 처리 방법을 모르는 영역·예시는 '모르는 대상'으로 FAIL.
#   제외: scripts/check-all.exclude (종류:이름 | 이유, 이유 필수). 허용: scripts/check-all-allow.txt (규칙|경로 글롭|이유).
# FAIL 이 하나라도 있으면 종료 코드 1. 값·비밀은 출력하지 않는다. 형제 영역은 읽기 전용이다.
# 사용: scripts/check-all.sh        환경(시험용): CHECK_ALL_WORKSPACE, CHECK_ALL_ONLY=1,2,...
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=python3
python3 -c 'import yaml' 2>/dev/null || { [ -x "$HERE/../.venv/bin/python" ] && PY="$HERE/../.venv/bin/python"; }
exec "$PY" -I "$HERE/check_all.py"
