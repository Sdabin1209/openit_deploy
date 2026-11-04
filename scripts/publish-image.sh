#!/usr/bin/env bash
# 영역 CI가 부르는 운영용 게시 인터페이스(D24). 이미지 하나를 서버의 로컬 레지스트리에 올리고 digest를 locks/images.lock 에 기록한다.
#
# 사용: scripts/publish-image.sh <서비스 이름> <이미지 ID|이미지 이름|tar 파일> [--registry host:port]
#   서비스 이름: survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console
#   레지스트리: --registry, 없으면 환경 변수 DEPLOY_REGISTRY, 없으면 state/registry.env
#   환경: DEPLOY_LOCK (기본 locks/images.lock)
# 종료 코드: 0 성공(또는 이미 같은 digest), 1 Docker 실행 파일/데몬에 닿지 않음, 2 사용법/서비스 이름이 목록에 없음, 3 필수 라벨 누락 또는 라벨 값이 계약 ImageLabels 를 어김, 4 이미지 없음·push·digest 확인 실패, 5 잠금 기록 실패
# 표준 출력 마지막 줄(기계가 읽는다): 계약 PublishResult JSON 한 줄(boundary-contracts v2.6.0). 성공 {"exit_code":0,"status":"PUBLISHED|UNCHANGED","service":…,"digest":…,"revision":…},
#   실패 {"exit_code":N,"service":…}(status·digest 없음). 예전의 `PUBLISHED <서비스> <digest> <revision>` 줄은 없다. --help 는 이 줄을 내지 않는다.
# 멱등: 같은 이미지를 다시 올리면 같은 digest이고 잠금·history는 바뀌지 않는다. 잠금은 flock 으로 직렬화하고 임시 파일에 쓴 뒤 바꿔 넣는다.
# 잠금 파일 형식은 publish-images.sh 와 같다: 머리말 한 줄 + 정렬된 KEY=value (<서비스>_DIGEST, <서비스>_REVISION, 외부 이미지 줄 유지).
set -euo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 항상 동작해야 한다. 데몬 감지는 인자를 확인한 뒤에 한다
source "$(dirname "$0")/lib.sh"
# 마지막 줄 PublishResult(계약): 어떤 종료 경로든 같은 자리에서 낸다(종료 코드 enum 0~5 밖이면 계약에 없는 코드라 내지 않는다)
PUB_STATUS=""; PUB_DIGEST=""; PUB_REV=""; PUB_JSON=1
emit_result() {
  local rc=$? svc="" out
  [ "$PUB_JSON" = 1 ] || return $rc
  case $rc in 0|1|2|3|4|5) ;; *) return $rc;; esac
  [[ "${SVC:-}" =~ ^[a-z][a-z0-9-]*$ ]] && svc=$SVC
  if [ $rc = 0 ]; then out=$(printf '{"exit_code":0,"status":"%s","service":"%s","digest":"%s","revision":"%s"}' "$PUB_STATUS" "$svc" "$PUB_DIGEST" "$PUB_REV")
  else out=$(printf '{"exit_code":%s%s%s}' "$rc" "${svc:+,\"service\":\"$svc\"}" "$( [[ "${REV:-}" =~ ^[0-9a-f]{7,40}$ ]] && printf ',"revision":"%s"' "$REV")"); fi
  # R7: 만드는 쪽이 내보내기 전에 계약 PublishResult 로 검증한다. 어기면 줄을 내지 않고(표준 출력 비움) 표준 오류에 사유(값 없이 위치만)를 쓰고, 성공(0)이었다면 0이 아닌 코드(70)로 끝낸다 — 영역 CI 가 틀린 결과를 제출하지 않게 한다
  if ! err=$("$DEPLOY_PY" -W ignore -I -c 'import json,sys
from boundary_contracts import validator
e = ["%s: %s 위반" % (list(x.path), x.validator) for x in validator("PublishResult").iter_errors(json.loads(sys.argv[1]))]
sys.exit("; ".join(e) if e else 0)' "$out" 2>&1); then
    echo "publish-image.sh: 결과가 계약 PublishResult 를 어긴다(내보내지 않는다): $err" >&2
    [ $rc = 0 ] && exit 70; return $rc
  fi
  printf '%s\n' "$out"
  return $rc
}
trap emit_result EXIT
usage() {
  cat <<USAGE
영역 CI가 이미지 하나를 올릴 때 쓴다. 로컬에서 build-images.sh 로 만든 이미지 전체를 올리려면 publish-images.sh(복수)를 쓴다.

사용: scripts/publish-image.sh <서비스 이름> <이미지 ID|이미지 이름|tar 파일> [--registry host:port]
  서비스 이름: $SERVICES (선택: $SERVICES_OPTIONAL)
  레지스트리: --registry, 없으면 환경 변수 DEPLOY_REGISTRY, 없으면 state/registry.env
  환경: DEPLOY_LOCK (기본 locks/images.lock)
종료 코드: 0 성공(또는 이미 같은 digest), 2 사용법/서비스 이름이 목록에 없음, 3 필수 라벨 누락, 4 이미지 없음·push·digest 확인 실패, 5 잠금 기록 실패, 1 Docker 실행 파일/데몬에 닿지 않음
자세한 계약: docs/ci.md
USAGE
}
case "${1:-}" in -h|--help) PUB_JSON=0; usage; exit 0;; esac
SVC="${1:-}"; SRC="${2:-}"; if [ $# -ge 2 ]; then shift 2; else shift $#; fi
REG="${DEPLOY_REGISTRY:-}"
while [ $# -gt 0 ]; do case "$1" in --registry) REG="${2:-}"; shift 2;; -h|--help) PUB_JSON=0; usage; exit 0;; *) echo "알 수 없는 인자: $1" >&2; usage >&2; exit 2;; esac; done
[ -n "$SVC" ] && [ -n "$SRC" ] || { usage >&2; exit 2; }
case " $SERVICES $SERVICES_OPTIONAL " in *" $SVC "*) ;; *) echo "거부: 서비스 이름 '$SVC' 이(가) 목록에 없다 ($SERVICES)" >&2; exit 2;; esac
if [ -z "$REG" ]; then
  RF="${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"
  [ -f "$RF" ] && REG=$(sed -n 's/^DEPLOY_REGISTRY=//p' "$RF")
fi
REG=${REG#http://}; REG=${REG#https://}; REG=${REG%/}
[ -n "$REG" ] || { echo "거부: 레지스트리 주소가 없다(--registry 또는 DEPLOY_REGISTRY)" >&2; exit 2; }
detect_docker   # 인자가 맞은 뒤에만 데몬을 확인한다(종료 코드 1: 데몬 불가)
LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; HIST="$(dirname "$LOCK")/history"; mkdir -p "$HIST"; [ -f "$LOCK" ] || : > "$LOCK"

# 이미지 얻기: tar 파일이면 docker load
IMG="$SRC"
if [ -f "$SRC" ]; then
  out=$("$DOCKER" load -i "$SRC" 2>&1) || { echo "$out" >&2; echo "거부: tar를 읽지 못했다" >&2; exit 4; }
  IMG=$(echo "$out" | tr -d '\r' | sed -n 's/^Loaded image: //p; s/^Loaded image ID: //p' | tail -1)
  [ -n "$IMG" ] || { echo "$out" >&2; echo "거부: tar에서 이미지를 찾지 못했다" >&2; exit 4; }
fi
"$DOCKER" image inspect "$IMG" >/dev/null 2>&1 || { echo "거부: 이미지가 없다: $IMG" >&2; exit 4; }
# 라벨 검사는 계약 ImageLabels 검증 하나다(필수 키 4개의 존재·빈 값·revision 형식·n/a 표기·오타 키를 스키마가 모두 본다). 예전에는 필수 키를 손으로 먼저 보고 계약 검증을 또 했다(이중 검사, U44).
# 검사를 못 한 경우(jsonschema 없음 등)도 통과가 아니다: 종료 코드 3.
vrc=0; vout=$(validate_image_labels "$IMG" "$SVC" 2>&1) || vrc=$?
[ $vrc = 0 ] || { echo "$vout" >&2; echo "거부: 이미지 라벨이 계약 ImageLabels 를 어기거나 검사하지 못했다(종료 코드 3): $SVC" >&2; exit 3; }
REV=$("$DOCKER" image inspect "$IMG" --format '{{index .Config.Labels "io.openit.revision"}}' | tr -d '\r')   # 태그 이름에 쓸 값만 읽는다(형식은 위 계약 검증이 보증한다)
TAGREV=$(echo "$REV" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-100)

# push 와 digest 확인(/v2/ 프로브, push, digest 읽기, 레지스트리 HEAD 대조)은 lib.sh 의 registry_publish_ref 하나가 한다(publish-images.sh 와 같은 함수). 시간 상한의 기본값과 근거도 lib.sh 한 곳이다
REF="$REG/openit/$SVC:build-$TAGREV"
"$DOCKER" tag "$IMG" "$REF"
registry_publish_ref "$REG" "$SVC" "build-$TAGREV" "$REF" || exit 4
DIGEST=$REGISTRY_DIGEST

# 잠금 기록은 lib.sh 의 lock_set 하나(flock 직렬화, 임시 파일 -> 바꿔 넣기, 같은 digest 면 변경 없음). 반환 3 = 이미 같은 digest
lrc=0; lock_set "$LOCK" "$SVC" "$DIGEST" "$REV" || lrc=$?
if [ $lrc = 3 ]; then
  echo "이미 같은 digest: $SVC $DIGEST (잠금 변경 없음)"; PUB_STATUS=UNCHANGED; PUB_DIGEST=$DIGEST; PUB_REV=$REV; exit 0
fi
[ $lrc = 0 ] || { echo "잠금 기록 실패" >&2; exit 5; }
echo "게시: $SVC@$DIGEST (revision $REV) -> $LOCK"; PUB_STATUS=PUBLISHED; PUB_DIGEST=$DIGEST; PUB_REV=$REV
