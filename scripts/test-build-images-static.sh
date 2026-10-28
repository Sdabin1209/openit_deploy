#!/usr/bin/env bash
# 정적 시험: build-images.sh 가 영역 소스 트리의 내부 경로를 읽지 않는다(구조 규칙: 영역은 서로의 구조를 모른다).
# 영역이 build/ 아래에 내는 산출물(VERSIONS.env, *.tag, BOUNDARY_TAG, SURVEY_SCHEMA_VERSION)만 읽을 수 있다.
# 왜 줄 검사인가: 읽는 동작이 cat/sed/source/tomllib 한 줄짜리라 구조화 파서가 필요 없다. 새로 읽는 경로가 생기면 이 시험이 걸려 산출물 파일로 바꾸게 한다.
HERE="$(cd "$(dirname "$0")" && pwd)"; F="$HERE/build-images.sh"; rc=0
bad=$(grep -nE '(cat|sed|source|head|tr)[^|;]*"\$CTX/[a-z-]+/(src|tests?|docs|schema|requirements|pyproject|package|[A-Za-z_]+/)' "$F" | grep -v '/build/' || true)
[ -z "$bad" ] && echo "ok: 영역 소스 트리 내부 경로를 읽지 않는다(build/ 산출물만)" || { echo "FAIL: 내부 경로를 읽는다:"; echo "$bad"; rc=1; }
grep -q 'ops_feedback/_schemas' "$F" && { echo "FAIL: ops-feedback 내부 경로 _schemas"; rc=1; } || echo "ok: ops-feedback _schemas 경로 없음"
grep -q 'requirements.lock' "$F" && { echo "FAIL: requirements.lock 경로"; rc=1; } || echo "ok: 잠금 파일 경로 없음"
[ $rc = 0 ] && echo "통과: build-images 정적 시험"; exit $rc
