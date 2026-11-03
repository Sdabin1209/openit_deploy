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
keys() { grep -E '^[A-Z0-9_]+=' "$1" | cut -d= -f1 | sort; }
# 서비스 digest 가 lib.sh SERVICES 전부 있는 잠금만 후보다(예전엔 "4개 이상" 고정이었다: 서비스가 4개이던 때의 숫자)
has_all_digests() { local sv v; for sv in $SERVICES; do v=$(echo "$sv" | tr 'a-z-' 'A-Z_'); grep -q "^${v}_DIGEST=" "$1" || return 1; done; }
if [ -z "$TO" ]; then
  for f in $(ls -1 "$H"/*.lock 2>/dev/null | sort -r); do
    has_all_digests "$f" || continue                          # 서비스 digest가 다 있는 것만
    [ "$(digests "$f")" != "$(digests "$LOCK")" ] || continue  # 현재와 같은 것은 건너뛴다
    TO=$f; break
  done
fi
[ -n "$TO" ] && [ -f "$TO" ] || die "되돌릴 이전 잠금이 없다(locks/history 비어 있음)"
has_all_digests "$TO" || die "이 잠금에는 서비스 digest 가 다 없다(lib.sh SERVICES 기준): $TO"
# 이미지만 되돌리는 코드 축 롤백은 같은 deploy 판(compose)의 잠금 사이에서만 성립한다. 잠금 전체(제3자 이미지 줄 포함)를 바꾸므로, 키 집합이 현재와 다르면(예: TLS 이전 잠금에는 STEP_CA_IMAGE 가 없다) compose 가 거부한다
if [ "$(keys "$TO")" != "$(keys "$LOCK")" ]; then
  # 어느 deploy 커밋인가(DC-REL.1): 잠금 파일 이름(YYYYmmddTHHMMSSZ)은 만든 시각이다. 그 시각에 compose.yaml 의 최신 커밋이 그 잠금과 짝인 deploy 판이다. 잠금 파일이 git 에 추적되면 그것을 추가한 커밋을 먼저 쓴다
  c=$(git -C "$DEPLOY_ROOT" log -1 --format='%h %s' --diff-filter=A -- "$TO" 2>/dev/null || true)
  if [ -z "$c" ]; then ts=$(basename "$TO" .lock | sed -E 's/^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z.*/\1-\2-\3T\4:\5:\6Z/'); c=$(git -C "$DEPLOY_ROOT" log -1 --until="$ts" --format='%h %s' -- compose.yaml 2>/dev/null || true); fi
  echo "이 잠금($(basename "$TO"))을 만든 deploy 커밋: ${c:-찾지 못했다(git 이력이 없다)}" >&2
  [ -z "$c" ] || echo "되돌리는 방법: git -C $DEPLOY_ROOT checkout ${c%% *}  (그 판의 compose·스크립트로 돌아간 뒤 rollback.sh 를 다시 부른다)" >&2
  echo "이 잠금은 다른 deploy 판(compose)과 짝이다: deploy 리포를 그 커밋으로 되돌려라. 현재 잠금에만 있는 키: $(comm -23 <(keys "$LOCK") <(keys "$TO") | tr '\n' ' ') / 그 잠금에만 있는 키: $(comm -13 <(keys "$LOCK") <(keys "$TO") | tr '\n' ' ')" >&2
  exit 2
fi
echo "롤백: $LOCK <- $TO"; diff <(digests "$LOCK") <(digests "$TO") || true
cp "$LOCK" "$H/$(date -u +%Y%m%dT%H%M%SZ)-before-rollback.lock"
cp "$TO" "$LOCK"
bash "$DEPLOY_ROOT/scripts/check-compose.sh" >/dev/null
if [ $APPLY = 1 ]; then bash "$DEPLOY_ROOT/scripts/up.sh" "$P"; fi
