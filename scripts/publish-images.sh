#!/usr/bin/env bash
# build/images.env 의 이미지를 로컬 레지스트리에 올리고 digest 잠금(locks/images.lock)을 갱신한다(D24).
# 이전 잠금은 locks/history/ 에 보관한다(롤백의 재료). 외부 이미지 줄(GATEWAY_IMAGE 등)은 그대로 둔다.
# 사용: publish-images.sh [영역 ...]   (비우면 build/images.env 전부)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; mkdir -p "$(dirname "$LOCK")/history"
source "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"   # DEPLOY_REGISTRY
only=" $* "
tmp=$(mktemp); cp "$LOCK" "$tmp"
while read -r area img commit; do
  [ "$only" = "  " ] || [[ "$only" == *" $area "* ]] || continue
  var=$(echo "$area" | tr 'a-z-' 'A-Z_')
  ref="$DEPLOY_REGISTRY/openit/$area:build-$commit"
  "$DOCKER" tag "$img" "$ref"
  out=$("$DOCKER" push "$ref" 2>&1) || { echo "$out"; die "push 실패: $ref"; }
  digest=$(echo "$out" | tr -d '\r' | sed -n 's/.*digest: \(sha256:[0-9a-f]\{64\}\).*/\1/p' | tail -1)
  [ -n "$digest" ] || { echo "$out"; die "digest를 읽지 못했다: $ref"; }
  # 레지스트리가 같은 digest를 아는지 확인한다.
  reg=$(curl -fsSI -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
        "http://${DEPLOY_REGISTRY}/v2/openit/$area/manifests/build-$commit" | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p')
  [ "$reg" = "$digest" ] || die "레지스트리 digest($reg)와 push 출력($digest)이 다르다"
  sed -i "/^${var}_DIGEST=/d; /^${var}_REVISION=/d" "$tmp"
  printf '%s_DIGEST=%s\n%s_REVISION=%s\n' "$var" "$digest" "$var" "$commit" >> "$tmp"
  echo "게시: openit/$area@$digest (커밋 $commit)"
done < "$DEPLOY_ROOT/build/images.env"
if ! cmp -s "$tmp" "$LOCK"; then
  cp "$LOCK" "$(dirname "$LOCK")/history/$(date -u +%Y%m%dT%H%M%SZ).lock"
  { echo "# 코드 축: 이미지 digest 잠금(D07). 손으로 고치지 않는다. publish-images.sh 와 rollback.sh 가 바꾼다."; grep -v '^#' "$tmp" | sort; } > "$LOCK"
fi
rm -f "$tmp"; echo "잠금: $LOCK"
