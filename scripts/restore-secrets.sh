#!/usr/bin/env bash
# secrets/ 복구. 사용: restore-secrets.sh <복호한 secrets.tar> <대상 폴더> --yes     (복호는 개인키를 가진 사람이 서버 밖에서/임시로 한다: runbook 4-6절)
# 대상 폴더는 없거나 비어 있어야 한다(기존 비밀을 덮어쓰지 않는다). 절대 경로·상위 경로(..)가 든 tar 는 거부한다. 풀고 나서 lib.sh secret_mode 대로 모드를 바로잡는다(값은 건드리지 않는다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
TAR=${1:?복호한 secrets.tar}; DST=${2:?대상 폴더}; [ "${3:-}" = --yes ] || die "--yes 가 필요하다"
[ -f "$TAR" ] || die "tar 가 없다: $TAR"
if [ -d "$DST" ] && [ -n "$(ls -A "$DST" 2>/dev/null)" ]; then die "대상 폴더가 비어 있지 않다: $DST (기존 비밀을 덮어쓰지 않는다)"; fi
# 목록을 먼저 변수로 받는다(점검 L3): `tar -tf | grep -q` 는 grep 이 일찍 끝나면 tar 가 SIGPIPE 로 실패하고 pipefail 때문에 이 검사가 조용히 건너뛰어졌다
TLIST=$(tar -tf "$TAR") || die "tar 목록을 읽지 못했다: $TAR"
if grep -qE '(^/|(^|/)\.\.(/|$))' <<<"$TLIST"; then die "tar 에 절대 경로 또는 .. 가 들어 있다: 거부"; fi
( umask 077; mkdir -p "$DST" ); chmod 700 "$DST"
( umask 077; tar -xf "$TAR" -C "$DST" --no-same-owner ); chmod 700 "$DST" "$DST/tokens" 2>/dev/null || true
for f in "$DST"/tokens/*; do [ -f "$f" ] && chmod "$(secret_mode "$(basename "$f")")" "$f"; done   # 모드 바로잡기(값은 건드리지 않는다)
for f in "$DST"/gateway-*.caddy; do [ -f "$f" ] && chmod 644 "$f"; done; [ ! -d "$DST/kiosk-config" ] || chmod -R u=rwX,go= "$DST/kiosk-config"
echo "복구: $DST ($(find "$DST" -type f | wc -l)개 파일). 이어서: bash scripts/check-secret-perms.sh $DST"
