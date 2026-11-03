#!/usr/bin/env bash
# rollback.sh 단독 시험(Docker 불필요, --no-apply, 가짜 history): (1) 서비스 digest 가 다 있는 잠금만 후보 (2) 키 집합이 현재와 다른 잠금(다른 deploy 판)으로는 멈춘다 (3) 같은 판의 이전 잠금으로는 되돌아간다.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; mkdir -p "$T/history"; F=0
ok() { local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; F=$((F+1)); fi; }
mk() { # mk <파일> <digest 값 한 글자> [빼는 키]  -- 현재 deploy 판의 잠금 모양(외부 이미지 줄 + 서비스 digest 줄)
  local f=$1 d=$2 skip=${3:-} k sv v; : > "$f"
  while IFS= read -r l; do k=${l%%=*}; [ "$k" != "$skip" ] && echo "$l" >> "$f"; done < <(grep -E '^[A-Z0-9_]+_IMAGE=' "$DEPLOY_ROOT/locks/images.lock")
  for sv in $SERVICES; do v=$(echo "$sv" | tr 'a-z-' 'A-Z_'); [ "${v}_DIGEST" != "$skip" ] && echo "${v}_DIGEST=sha256:$(printf "$d%.0s" $(seq 64))" >> "$f"; done
  return 0
}
export DEPLOY_LOCK="$T/images.lock"
mk "$DEPLOY_LOCK" b
rb() { bash "$HERE/rollback.sh" --no-apply deploy-rbtest; }
# (1) 서비스 digest 가 하나 빠진 잠금은 후보가 아니다 -> 더 오래된 온전한 잠금을 고른다
mk "$T/history/20260101T000000Z.lock" a; mk "$T/history/20260102T000000Z.lock" c "KIOSK_FRONTEND_DIGEST"
rb > "$T/o1" 2>&1; ok "digest 가 빠진 잠금은 건너뛰고 온전한 이전 잠금으로 되돌린다" bash -c "grep -q 'sha256:a' '$DEPLOY_LOCK' && grep -q '20260101T000000Z' '$T/o1'"
# (2) 키 집합이 다른(다른 deploy 판) 잠금: 멈추고 잠금은 그대로
mk "$DEPLOY_LOCK" b; rm -f "$T/history"/*.lock; mk "$T/history/20260103T000000Z.lock" a "STEP_CA_IMAGE"; cp "$DEPLOY_LOCK" "$T/before"
rb > "$T/o2" 2>&1; rc=$?
ok "TLS 이전처럼 키 집합이 다른 잠금은 다른 deploy 판과 짝이라고 말하고 멈춘다(종료 2)" bash -c "[ $rc = 2 ] && grep -q '다른 deploy 판' '$T/o2' && grep -q 'STEP_CA_IMAGE' '$T/o2'"
ok "그때 현재 잠금은 바뀌지 않는다" cmp -s "$DEPLOY_LOCK" "$T/before"
ok "DC-REL.1 메시지가 그 잠금을 만든 deploy 커밋 해시와 되돌리는 방법(git checkout)을 짚는다" bash -c 'grep -Eq "만든 deploy 커밋: ([0-9a-f]{7,}|찾지 못했다)" "$1" && grep -q "되돌리는 방법\|찾지 못했다" "$1"' _ "$T/o2"
# (3) 같은 판의 이전 잠금
rm -f "$T/history"/*.lock; mk "$T/history/20260104T000000Z.lock" a; rb > "$T/o3" 2>&1
ok "같은 판의 이전 잠금으로 되돌아간다" bash -c "grep -q 'sha256:a' '$DEPLOY_LOCK'"
echo; [ $F = 0 ] && echo "통과: rollback 단독 시험" || { echo "실패: $F건"; exit 1; }
