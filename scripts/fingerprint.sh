#!/usr/bin/env bash
# 파일 저장소 볼륨의 논리 지문(폴더 목록 + 파일 내용 해시, 임시 폴더 .tmp 제외). 서비스가 멈춘 상태에서 복구 왕복 시험(E2E 단계 9)이 쓴다. 사용: fingerprint.sh <저장소 이름>   환경: DEPLOY_PROJECT
# 표준 도구(find, sha256sum)만 쓴다: 옛 backup_tool.py finger 의 SQLite 덤프 해시는 운영 볼륨에 SQLite 가 없어 뺐다(ADR 0038).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${DEPLOY_PROJECT:-deploy}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
[ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금 파일에 없다"
h=$("$DOCKER" run --rm -v "${P}_${1}:/src:ro" "$UTIL" sh -c 'cd /src && { find . -mindepth 1 -type d ! -path "./.tmp" ! -path "./.tmp/*" | LC_ALL=C sort; find . -type f ! -path "./.tmp/*" -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum; } | sha256sum' | tr -d '\r' | cut -c1-64)
printf '{"fingerprint": "%s"}\n' "$h"
