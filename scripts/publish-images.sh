#!/usr/bin/env bash
# build/images.env 의 이미지를 로컬 레지스트리에 올리고 digest 잠금(locks/images.lock)을 갱신한다(D24).
# 이전 잠금은 locks/history/ 에 보관한다(롤백의 재료). 외부 이미지 줄(GATEWAY_IMAGE 등)은 그대로 둔다.
# 사용: publish-images.sh [영역 ...]   (비우면 build/images.env 의 기본 영역 전부. 선택 이미지(model-serving-gpu, 13GB)는 이름을 줄 때만 올린다)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
IMAGES_ENV="${DEPLOY_IMAGES_ENV:-$DEPLOY_ROOT/build/images.env}"   # 시험이 자기 기록 파일을 준다(DEPLOY_LOCK 과 같은 방식)
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; mkdir -p "$(dirname "$LOCK")/history"
source "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"   # DEPLOY_REGISTRY
# 레지스트리 호출 상한과 push·digest 확인·잠금 기록은 lib.sh 의 registry_publish_ref, lock_set 이 한다(publish-image.sh 와 같은 함수, 기본값과 근거는 lib.sh 한 곳)
lockargs=()
only=" $* "
while read -r area img commit _; do   # 4번째 열(bc=..,mr=.. 빌드 태그 기록, 속도 개선의 --reuse-build 용)은 무시한다
  [ "$only" = "  " ] || [[ "$only" == *" $area "* ]] || continue
  # 선택 이미지는 기본 경로에 넣지 않는다: 기록이 남아 있어도 기본 게시·E2E 가 그 이미지에 의존하지 않는다
  if [ "$only" = "  " ] && [[ " $SERVICES_OPTIONAL " == *" $area "* ]]; then echo "건너뜀: $area (선택 이미지, 이름을 줄 때만 게시)"; continue; fi
  if [ "$area" = model-serving-gpu ]; then gpu_record_valid "$IMAGES_ENV" >/dev/null || die "GPU 이미지 기록이 유효하지 않다: $(gpu_record_valid "$IMAGES_ENV" 2>&1 >/dev/null | tail -1)"; fi
  "$DOCKER" image inspect "$img" >/dev/null 2>&1 || die "이미지가 이 호스트에 없다: $img (다시 빌드: bash scripts/build-images.sh $area)"
  # 게시 전 라벨 검사(계약 ImageLabels). 어긋나면 올리지 않는다
  vrc=0; vout=$(validate_image_labels "$img" "$area" 2>&1) || vrc=$?
  [ $vrc = 0 ] || { echo "$vout"; die "이미지 라벨이 계약 ImageLabels 를 어기거나 검사하지 못했다: $area ($img). 라벨을 붙이는 쪽을 고친다(docs/runbook.md 이미지 라벨)"; }
  ref="$DEPLOY_REGISTRY/openit/$area:build-$commit"
  "$DOCKER" tag "$img" "$ref"
  registry_publish_ref "$DEPLOY_REGISTRY" "$area" "build-$commit" "$ref" || die "게시하지 못했다: $area ($ref)"
  lockargs+=("$area" "$REGISTRY_DIGEST" "$commit")
  echo "게시: openit/$area@$REGISTRY_DIGEST (커밋 $commit)"
done < "$IMAGES_ENV"
# 잠금은 모든 이미지를 올린 뒤 한 번에 기록한다(중간에 실패하면 잠금은 그대로다). 반환 3 = 바뀐 것 없음
if [ ${#lockargs[@]} -gt 0 ]; then lrc=0; lock_set "$LOCK" "${lockargs[@]}" || lrc=$?; [ $lrc = 0 ] || [ $lrc = 3 ] || die "잠금 기록 실패(종료 코드 $lrc): $LOCK"; fi
echo "잠금: $LOCK"
