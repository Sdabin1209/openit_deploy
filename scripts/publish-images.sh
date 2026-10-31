#!/usr/bin/env bash
# build/images.env 의 이미지를 로컬 레지스트리에 올리고 digest 잠금(locks/images.lock)을 갱신한다(D24).
# 이전 잠금은 locks/history/ 에 보관한다(롤백의 재료). 외부 이미지 줄(GATEWAY_IMAGE 등)은 그대로 둔다.
# 사용: publish-images.sh [영역 ...]   (비우면 build/images.env 의 기본 영역 전부. 선택 이미지(model-serving-gpu, 13GB)는 이름을 줄 때만 올린다)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; mkdir -p "$(dirname "$LOCK")/history"
source "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"   # DEPLOY_REGISTRY
# 레지스트리 호출 상한(FAULT_POLICY 4: 의존 호출에 연결·읽기 timeout, 무한 대기 금지). 값은 측정한 것이 아니라 판단이다(측정 안 함), 환경 변수로 바꾼다.
#  PUBLISH_CONNECT_TIMEOUT(3s): 같은 호스트의 로컬 레지스트리라 연결은 즉시여야 한다. 3초에 안 되면 장애로 본다.
#  PUBLISH_PROBE_TIMEOUT(5s): push 전에 /v2/ 응답을 확인하는 전체 상한. 레지스트리가 멈춰 있으면(pause: 연결은 되고 응답이 없다) docker push 가 끝없이 기다리므로 먼저 걸러 종료 코드 1/4 로 스스로 실패한다.
#  PUBLISH_HEAD_TIMEOUT(15s): digest 확인용 HEAD 요청 전체 상한.
#  PUBLISH_PUSH_TIMEOUT(900s): docker push 전체 상한. 이미지 크기·디스크 속도는 측정하지 않았다(작은 이미지는 수 초, 13GB GPU 이미지는 더 걸릴 수 있어 넉넉히 잡은 시작값). 초과하면 124 로 실패한다.
CT=${PUBLISH_CONNECT_TIMEOUT:-3}; PROBE_T=${PUBLISH_PROBE_TIMEOUT:-5}; HEAD_T=${PUBLISH_HEAD_TIMEOUT:-15}; PUSH_T=${PUBLISH_PUSH_TIMEOUT:-900}
only=" $* "
tmp=$(mktemp); cp "$LOCK" "$tmp"
while read -r area img commit _; do   # 4번째 열(bc=..,mr=.. 빌드 태그 기록, 속도 개선의 --reuse-build 용)은 무시한다
  [ "$only" = "  " ] || [[ "$only" == *" $area "* ]] || continue
  # 선택 이미지는 기본 경로에 넣지 않는다: 기록이 남아 있어도 기본 게시·E2E 가 그 이미지에 의존하지 않는다
  if [ "$only" = "  " ] && [[ " $SERVICES_OPTIONAL " == *" $area "* ]]; then echo "건너뜀: $area (선택 이미지, 이름을 줄 때만 게시)"; continue; fi
  if [ "$area" = model-serving-gpu ]; then gpu_record_valid "$DEPLOY_ROOT/build/images.env" >/dev/null || die "GPU 이미지 기록이 유효하지 않다: $(gpu_record_valid "$DEPLOY_ROOT/build/images.env" 2>&1 >/dev/null | tail -1)"; fi
  "$DOCKER" image inspect "$img" >/dev/null 2>&1 || die "이미지가 이 호스트에 없다: $img (다시 빌드: bash scripts/build-images.sh $area)"
  # 게시 전 라벨 검사(계약 ImageLabels). 어긋나면 올리지 않는다
  vrc=0; vout=$(validate_image_labels "$img" "$area" 2>&1) || vrc=$?
  [ $vrc = 0 ] || { echo "$vout"; die "이미지 라벨이 계약 ImageLabels 를 어기거나 검사하지 못했다: $area ($img). 라벨을 붙이는 쪽을 고친다(docs/runbook.md 이미지 라벨)"; }
  var=$(echo "$area" | tr 'a-z-' 'A-Z_')
  ref="$DEPLOY_REGISTRY/openit/$area:build-$commit"
  "$DOCKER" tag "$img" "$ref"
  curl -fsS -o /dev/null --connect-timeout "$CT" --max-time "$PROBE_T" "http://${DEPLOY_REGISTRY}/v2/" || die "레지스트리가 응답하지 않는다(${PROBE_T}초): ${DEPLOY_REGISTRY}"
  prc=0; out=$(timeout "$PUSH_T" "$DOCKER" push "$ref" 2>&1) || prc=$?
  if [ $prc = 124 ]; then echo "$out" | tail -3; die "push 시간 초과(${PUSH_T}초, timeout 종료 코드 124): $ref (PUBLISH_PUSH_TIMEOUT 로 바꿀 수 있다)"; fi
  [ $prc = 0 ] || { echo "$out"; die "push 실패(종료 코드 $prc): $ref"; }
  digest=$(echo "$out" | tr -d '\r' | sed -n 's/.*digest: \(sha256:[0-9a-f]\{64\}\).*/\1/p' | tail -1)
  [ -n "$digest" ] || { echo "$out"; die "digest를 읽지 못했다: $ref"; }
  # 레지스트리가 같은 digest를 아는지 확인한다.
  reg=$(curl -fsSI --connect-timeout "$CT" --max-time "$HEAD_T" -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
        "http://${DEPLOY_REGISTRY}/v2/openit/$area/manifests/build-$commit" | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p') || reg=""   # 레지스트리 HEAD 가 실패해도(set -e) 아래의 digest 불일치 사유 출력이 돌게 한다
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
