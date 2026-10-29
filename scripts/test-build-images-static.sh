#!/usr/bin/env bash
# 정적 시험: build-images.sh 가 영역 소스 트리의 내부 경로를 읽지 않는다(구조 규칙: 영역은 서로의 구조를 모른다).
# 영역이 build/ 아래에 내는 산출물(VERSIONS.env, *.tag, BOUNDARY_TAG, SURVEY_SCHEMA_VERSION)만 읽을 수 있다.
# 왜 줄 검사인가: 읽는 동작이 cat/sed/source/tomllib 한 줄짜리라 구조화 파서가 필요 없다. 새로 읽는 경로가 생기면 이 시험이 걸려 산출물 파일로 바꾸게 한다.
HERE="$(cd "$(dirname "$0")" && pwd)"; F="$HERE/build-images.sh"; rc=0
bad=$(grep -nE '(cat|sed|source|head|tr)[^|;]*"\$CTX/[a-z-]+/(src|tests?|docs|schema|requirements|pyproject|package|[A-Za-z_]+/)' "$F" | grep -v '/build/' || true)
[ -z "$bad" ] && echo "ok: 영역 소스 트리 내부 경로를 읽지 않는다(build/ 산출물만)" || { echo "FAIL: 내부 경로를 읽는다:"; echo "$bad"; rc=1; }
grep -q 'ops_feedback/_schemas' "$F" && { echo "FAIL: ops-feedback 내부 경로 _schemas"; rc=1; } || echo "ok: ops-feedback _schemas 경로 없음"
grep -q 'requirements.lock' "$F" && { echo "FAIL: requirements.lock 경로"; rc=1; } || echo "ok: 잠금 파일 경로 없음"
# 영역 내부 파일의 버전을 직접 읽지 않는다(model-runtime pyproject.toml, kiosk-frontend package.json): 라벨 값은 deploy 기준표(lib.sh)나 이미지 산출물에서 얻는다(ADR 0041)
for pat in 'pyproject\.toml' 'package\.json' 'tomllib' 'mr_version'; do
  hit=$(grep -nE "$pat" "$F" | grep -v '^[0-9]*:[[:space:]]*#' || true)
  [ -z "$hit" ] && echo "ok: build-images.sh 가 $pat 를 읽지 않는다" || { echo "FAIL: 영역 내부 버전 파일/파서 사용 ($pat):"; echo "$hit" | cut -c1-160; rc=1; }
done
grep -nE 'APP_VERSION' "$F" | grep -v '^[0-9]*:[[:space:]]*#' | grep -q . && { echo "FAIL: APP_VERSION 을 deploy 가 넘긴다(영역 Dockerfile 의 기본값을 쓴다)"; rc=1; } || echo "ok: APP_VERSION 을 넘기지 않는다(영역이 정한다)"
[ $rc = 0 ] && echo "통과: build-images 정적 시험"; exit $rc
