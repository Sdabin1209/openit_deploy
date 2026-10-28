#!/usr/bin/env bash
# 영역 CI가 부르는 운영용 게시 인터페이스(D24). 이미지 하나를 서버의 로컬 레지스트리에 올리고 digest를 locks/images.lock 에 기록한다.
#
# 사용: scripts/publish-image.sh <서비스 이름> <이미지 ID|이미지 이름|tar 파일> [--registry host:port]
#   서비스 이름: survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console
#   레지스트리: --registry, 없으면 환경 변수 DEPLOY_REGISTRY, 없으면 state/registry.env
#   환경: DEPLOY_LOCK (기본 locks/images.lock)
# 종료 코드: 0 성공(또는 이미 같은 digest), 1 Docker 실행 파일/데몬에 닿지 않음, 2 사용법/서비스 이름이 목록에 없음, 3 필수 라벨 누락, 4 이미지 없음·push·digest 확인 실패, 5 잠금 기록 실패
# 표준 출력 마지막 줄(기계가 읽는다): PUBLISHED <서비스> <digest> <revision> | UNCHANGED <서비스> <digest> <revision>
# 멱등: 같은 이미지를 다시 올리면 같은 digest이고 잠금·history는 바뀌지 않는다. 잠금은 flock 으로 직렬화하고 임시 파일에 쓴 뒤 바꿔 넣는다.
# 잠금 파일 형식은 publish-images.sh 와 같다: 머리말 한 줄 + 정렬된 KEY=value (<서비스>_DIGEST, <서비스>_REVISION, 외부 이미지 줄 유지).
set -euo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 항상 동작해야 한다. 데몬 감지는 인자를 확인한 뒤에 한다
source "$(dirname "$0")/lib.sh"
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
case "${1:-}" in -h|--help) usage; exit 0;; esac
SVC="${1:-}"; SRC="${2:-}"; if [ $# -ge 2 ]; then shift 2; else shift $#; fi
REG="${DEPLOY_REGISTRY:-}"
while [ $# -gt 0 ]; do case "$1" in --registry) REG="${2:-}"; shift 2;; -h|--help) usage; exit 0;; *) echo "알 수 없는 인자: $1" >&2; usage >&2; exit 2;; esac; done
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
label() { "$DOCKER" image inspect "$IMG" --format "{{index .Config.Labels \"$1\"}}" | tr -d '\r'; }
# 필수 라벨(D50): service, revision, contracts.boundary, contracts.survey-schema. turn-engine·model-runtime 은 해당 없으면 없어도 된다.
for k in io.openit.service io.openit.revision io.openit.contracts.boundary io.openit.contracts.survey-schema; do
  v=$(label "$k"); { [ -n "$v" ] && [ "$v" != "<no value>" ]; } || { echo "거부: 필수 라벨 없음 또는 빈 값: $k" >&2; exit 3; }
done
REV=$(label io.openit.revision); case "$REV" in unknown|"") echo "거부: io.openit.revision 이 unknown 이다" >&2; exit 3;; esac
TAGREV=$(echo "$REV" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-100)

# 레지스트리 호출 상한(FAULT_POLICY 4: 의존 호출에 연결·읽기 timeout, 무한 대기 금지). 값은 측정한 것이 아니라 판단이다(측정 안 함), 환경 변수로 바꾼다.
#  PUBLISH_CONNECT_TIMEOUT(3s): 같은 호스트의 로컬 레지스트리라 연결은 즉시여야 한다. 3초에 안 되면 장애로 본다.
#  PUBLISH_PROBE_TIMEOUT(5s): push 전에 /v2/ 응답을 확인하는 전체 상한. 레지스트리가 멈춰 있으면(pause: 연결은 되고 응답이 없다) docker push 가 끝없이 기다리므로 먼저 걸러 종료 코드 1/4 로 스스로 실패한다.
#  PUBLISH_HEAD_TIMEOUT(15s): digest 확인용 HEAD 요청 전체 상한.
#  PUBLISH_PUSH_TIMEOUT(900s): docker push 전체 상한. 이미지 크기·디스크 속도는 측정하지 않았다(작은 이미지는 수 초, 13GB GPU 이미지는 더 걸릴 수 있어 넉넉히 잡은 시작값). 초과하면 124 로 실패한다.
CT=${PUBLISH_CONNECT_TIMEOUT:-3}; PROBE_T=${PUBLISH_PROBE_TIMEOUT:-5}; HEAD_T=${PUBLISH_HEAD_TIMEOUT:-15}; PUSH_T=${PUBLISH_PUSH_TIMEOUT:-900}
# push 와 digest 확인(레지스트리가 아는 digest와 push 출력이 같아야 한다)
REF="$REG/openit/$SVC:build-$TAGREV"
"$DOCKER" tag "$IMG" "$REF"
curl -fsS -o /dev/null --connect-timeout "$CT" --max-time "$PROBE_T" "http://$REG/v2/" 2>/dev/null || { echo "거부: 레지스트리가 응답하지 않는다(${PROBE_T}초): $REG" >&2; exit 4; }
out=$(timeout "$PUSH_T" "$DOCKER" push "$REF" 2>&1); prc=$?
[ $prc != 124 ] || { echo "$out" | tail -3 >&2; echo "거부: push 시간 초과(${PUSH_T}초, timeout 종료 코드 124): $REF (PUBLISH_PUSH_TIMEOUT 로 바꿀 수 있다)" >&2; exit 4; }
[ $prc = 0 ] || { echo "$out" | tail -3 >&2; echo "거부: push 실패(종료 코드 $prc): $REF" >&2; exit 4; }
DIGEST=$(echo "$out" | tr -d '\r' | sed -n 's/.*digest: \(sha256:[0-9a-f]\{64\}\).*/\1/p' | tail -1)
[ -n "$DIGEST" ] || { echo "$out" | tail -3 >&2; echo "거부: digest 를 읽지 못했다" >&2; exit 4; }
reg=$(curl -fsSI --connect-timeout "$CT" --max-time "$HEAD_T" -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
      "http://$REG/v2/openit/$SVC/manifests/build-$TAGREV" 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p') || reg=""
[ "$reg" = "$DIGEST" ] || { echo "거부: 레지스트리 digest('$reg')와 push 출력('$DIGEST')이 다르다" >&2; exit 4; }

# 잠금 기록(직렬화, 임시 파일 -> 바꿔 넣기). 같은 digest면 아무것도 바꾸지 않는다
VAR=$(echo "$SVC" | tr 'a-z-' 'A-Z_')
exec 9>"$LOCK.lock"; flock 9
CUR=$(sed -n "s/^${VAR}_DIGEST=//p" "$LOCK")
if [ "$CUR" = "$DIGEST" ] && [ "$(sed -n "s/^${VAR}_REVISION=//p" "$LOCK")" = "$REV" ]; then
  echo "이미 같은 digest: $SVC $DIGEST (잠금 변경 없음)"; echo "UNCHANGED $SVC $DIGEST $REV"; exit 0
fi
tmp=$(mktemp "$LOCK.XXXXXX")
{ grep -v '^#' "$LOCK" | grep -v "^${VAR}_DIGEST=" | grep -v "^${VAR}_REVISION=" || true; printf '%s_DIGEST=%s\n%s_REVISION=%s\n' "$VAR" "$DIGEST" "$VAR" "$REV"; } > "$tmp.body"
{ echo "# 코드 축: 이미지 digest 잠금(D07). 손으로 고치지 않는다. publish-image(s).sh 와 rollback.sh 가 바꾼다."; sort "$tmp.body"; } > "$tmp" || { rm -f "$tmp" "$tmp.body"; echo "잠금 기록 실패" >&2; exit 5; }
rm -f "$tmp.body"
if [ -s "$LOCK" ]; then cp "$LOCK" "$HIST/$(date -u +%Y%m%dT%H%M%S%NZ).lock"; fi
mv "$tmp" "$LOCK" || { echo "잠금 기록 실패" >&2; exit 5; }
echo "게시: $SVC@$DIGEST (revision $REV) -> $LOCK"; echo "PUBLISHED $SVC $DIGEST $REV"
