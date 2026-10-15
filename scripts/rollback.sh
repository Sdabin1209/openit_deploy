#!/usr/bin/env bash
# 코드 축 롤백: digest 잠금을 이전 것으로 되돌리고 적용한다(D07). 내용 축(릴리스 활성 포인터)은 건드리지 않는다(게이트의 몫).
# 사용: rollback.sh [--to <잠금 파일>] [--no-apply] [프로젝트]
#  기본은 locks/history/ 에서 현재와 다른 가장 최근 잠금. 현재 잠금은 history에 남기므로 롤백을 다시 되돌릴 수도 있다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}; H="$(dirname "$LOCK")/history"
TO=""; APPLY=1
while [ $# -gt 0 ]; do case "$1" in --to) TO=$2; shift 2;; --no-apply) APPLY=0; shift;; *) break;; esac; done
P=${1:-${DEPLOY_PROJECT:-deploy}}
digests() { grep -E '_DIGEST=' "$1" | sort; }
if [ -z "$TO" ]; then
  for f in $(ls -1 "$H"/*.lock 2>/dev/null | sort -r); do
    [ "$(digests "$f" | wc -l)" -ge 4 ] || continue          # 서비스 digest가 다 있는 것만
    [ "$(digests "$f")" != "$(digests "$LOCK")" ] || continue  # 현재와 같은 것은 건너뛴다
    TO=$f; break
  done
fi
[ -n "$TO" ] && [ -f "$TO" ] || die "되돌릴 이전 잠금이 없다(locks/history 비어 있음)"
echo "롤백: $LOCK <- $TO"; diff <(digests "$LOCK") <(digests "$TO") || true
cp "$LOCK" "$H/$(date -u +%Y%m%dT%H%M%SZ)-before-rollback.lock"
cp "$TO" "$LOCK"
bash "$DEPLOY_ROOT/scripts/check-compose.sh" >/dev/null
if [ $APPLY = 1 ]; then bash "$DEPLOY_ROOT/scripts/up.sh" "$P"; fi
