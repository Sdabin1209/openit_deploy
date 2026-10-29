#!/usr/bin/env bash
# 버전 표 드리프트 점검(ADR 0042). 기준은 scripts/lib.sh 의 표(DEPLOY_BC_TAG, DEPLOY_MR_TAG, DEPLOY_SS_TAG) 하나다.
# **빌드된 이미지의 라벨**(영역이 이미지에 스스로 단 선언, D50·계약 ImageLabels)을 표와 비교한다. 영역 소스 파일(requirements, Dockerfile ARG, 스크립트)을 읽지 않는다:
# 영역마다 계약 고정을 적는 이름·위치가 달라(BOUNDARY_VERSION, BOUNDARY_CONTRACT[S], requirements 핀 …) deploy 가 그 구조를 하나씩 배워 따라가는 것은 구조 규칙 1·6 에 어긋난다.
#   io.openit.contracts.boundary   모든 이미지가 표의 DEPLOY_BC_TAG 와 같아야 한다
#   io.openit.model-runtime        (선택 라벨) 있으면 n/a 이거나 표의 DEPLOY_MR_TAG 와 같아야 한다
#   io.openit.contracts.survey-schema  n/a 이거나 표의 문진 스키마 주 버전(DEPLOY_SS_TAG 의 정수)과 같아야 한다
# 대상 이미지 = build/images.env 의 기록(build-images.sh 가 쓴다). model-serving-gpu 는 로컬에 있을 때만 본다(13GB, 기본 빌드가 아니다).
# 종료 코드: 0 모두 같다, 1 어긋남(서비스·라벨·값을 출력), 3 **검증하지 못했다**(images.env 가 없거나 이미지가 로컬에 없거나 docker 를 못 쓴다). 3 은 통과가 아니다:
#   check-all 은 SKIP(검증 안 함)으로, E2E 는 빌드 뒤에 이 점검을 불러 3 을 실패로 본다. 왜 FAIL 이 아니라 3 인가: 이미지를 아직 안 만든 개발 중 check-all 이 FAIL 로 막히면 안 되고, 그렇다고 통과로 세면 안 된다.
# 사용: check-versions.sh      환경(시험용): CHECK_VERSIONS_IMAGES_ENV(기본 build/images.env), DOCKER(가짜 docker). 표를 덮어쓰는 환경 변수(BOUNDARY_TAG_ALL, MODEL_RUNTIME_TAG_ALL)는 무시한다.
set -uo pipefail
export DEPLOY_NO_DOCKER=1
unset BOUNDARY_TAG_ALL MODEL_RUNTIME_TAG_ALL
source "$(dirname "$0")/lib.sh"
ENVF="${CHECK_VERSIONS_IMAGES_ENV:-$DEPLOY_ROOT/build/images.env}"
SS_MAJOR=$(sed -n 's/^survey-schema-v\([0-9][0-9]*\)\..*/\1/p' <<<"$DEPLOY_SS_TAG")
echo "기준 표(scripts/lib.sh): boundary-contracts $DEPLOY_BC_TAG, model-runtime $DEPLOY_MR_TAG, 문진 스키마 주 버전 ${SS_MAJOR:-?}"
[ -s "$ENVF" ] || { echo "검증하지 못했다: 빌드 기록이 없다($ENVF). bash scripts/build-images.sh 뒤에 다시 (통과가 아니다)"; exit 3; }
D="${DOCKER:-docker}"; command -v "$D" >/dev/null 2>&1 && "$D" info >/dev/null 2>&1 || { echo "검증하지 못했다: docker 를 쓸 수 없다 (통과가 아니다)"; exit 3; }
bad=0; seen=0; missing=""
while read -r name img _; do
  case "$name" in ""|\#*) continue;; esac
  if ! labels=$("$D" image inspect "$img" --format '{{json .Config.Labels}}' 2>/dev/null | tr -d '\r'); then
    [ "$name" = model-serving-gpu ] && continue
    missing="$missing $name"; continue
  fi
  seen=$((seen+1))
  out=$(python3 -I - "$name" "$DEPLOY_BC_TAG" "$DEPLOY_MR_TAG" "${SS_MAJOR:-}" "$labels" <<'PY'
import json, sys
name, bc, mr, ss, raw = sys.argv[1:6]
L = json.loads(raw or "null") or {}
bad = []
def want(key, ok_values, shown):
    v = L.get(key)
    if v not in ok_values: bad.append(f"{name}: {key} {v!r} (표: {shown})")
want("io.openit.contracts.boundary", {bc}, bc)
if "io.openit.model-runtime" in L: want("io.openit.model-runtime", {"n/a", mr}, f"n/a 또는 {mr}")   # 선택 라벨(ImageLabels): 없으면 쓰지 않는 이미지(kiosk-frontend). 있는데 틀리면 어긋남
want("io.openit.contracts.survey-schema", {"n/a", ss}, f"n/a 또는 {ss}")
print("\n".join(bad))
PY
  )
  if [ -n "$out" ]; then while IFS= read -r l; do echo "  다름: $l"; bad=$((bad+1)); done <<<"$out"; fi
done < "$ENVF"
[ -z "$missing" ] || { echo "검증하지 못했다: 로컬에 이미지가 없다:$missing (build-images.sh 를 다시) (통과가 아니다)"; [ $bad = 0 ] && exit 3; }
[ $seen -gt 0 ] || { echo "검증하지 못했다: 검사한 이미지가 없다"; exit 3; }
if [ $bad -gt 0 ]; then echo "실패: 이미지 라벨이 표와 다른 곳 ${bad}건. 영역이 표의 태그로 다시 빌드·게시하거나 표를 바꾼다(deploy)"; exit 1; fi
echo "통과: 이미지 ${seen}개의 계약·model-runtime·문진 스키마 라벨이 표와 같다"
