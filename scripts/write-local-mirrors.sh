#!/usr/bin/env bash
# 원격이 동결된 동안 의존 리포(boundary-contracts, link, model-runtime, survey-service)를 로컬 리포에서 받는 git 설정을 build/gitconfig-local-mirrors 에 쓴다(구조 점검 S14).
# 왜 git 표준 url.<base>.insteadOf 하나인가(git-config(1)): 설치 명령(pip install git+ssh://...@태그)을 바꾸지 않고 주소만 로컬 경로로 바꿔 태그 설치 경로를 그대로 쓴다. 다른 우회(복사본, 경로 직접 설치)를 두지 않는다.
# 사용: scripts/write-local-mirrors.sh [워크스페이스 루트]  →  GIT_CONFIG_GLOBAL=build/gitconfig-local-mirrors pip install git+ssh://git@github.com/Sdabin1209/openit_link.git@<태그>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WS="${1:-${WORKSPACE:-}}"
if [ -z "$WS" ]; then   # 기본: 이 리포(또는 그 worktree)가 <워크스페이스>/deploy 아래에 있다(deploy/build/ 안에도 영역 사본이 있어 이름 "deploy" 폴더의 부모로 정한다)
  d="$ROOT"; while [ "$d" != / ] && [ "$(basename "$d")" != deploy ]; do d="$(dirname "$d")"; done; WS="$(dirname "$d")"
fi
[ -d "$WS" ] || { echo "워크스페이스 루트를 못 찾았다: 인자로 준다" >&2; exit 2; }
OUT="$ROOT/build/gitconfig-local-mirrors"; mkdir -p "$ROOT/build"
{
  echo "# scripts/write-local-mirrors.sh 가 만든다(S14). 손으로 고치지 않는다. 쓰는 법: GIT_CONFIG_GLOBAL=<이 파일> pip install git+ssh://git@github.com/Sdabin1209/openit_<이름>.git@<태그>"
  for r in boundary-contracts link model-runtime survey-service; do
    [ -d "$WS/$r/.git" ] || [ -f "$WS/$r/.git" ] || { echo "리포가 없다: $WS/$r" >&2; exit 2; }
    printf '[url "%s"]\n' "$WS/$r"
    for p in "ssh://git@github.com/Sdabin1209/openit_$r.git" "git@github.com:Sdabin1209/openit_$r.git" "https://github.com/Sdabin1209/openit_$r.git"; do printf '\tinsteadOf = %s\n' "$p"; done
  done
} > "$OUT"
echo "$OUT"
