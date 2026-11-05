#!/usr/bin/env bash
# 출발 컨테이너와 같은 망에 붙은 클라이언트 컨테이너(UTIL 이미지)에서 탐침 하나를 돌린다. 사용: client-probe.sh <출발 컨테이너> <루트 인증서 파일> <e2e_probe.py 인자...>
# 출발 컨테이너의 망 목록은 docker inspect 로 바깥에서 읽는다(영역 안으로 들어가지 않는다, 구조 규칙 1·6, CONVENTIONS 13절). 도달 여부는 망 소속이 정하므로 같은 망이면 출발 컨테이너와 같은 결과다.
# 인증서 검증을 끄지 않는다: SSL_CERT_FILE 이 step-ca 루트를 가리킨다. 종료 코드는 탐침의 것, 출발 컨테이너가 없으면 3.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
SRC=${1:?사용: client-probe.sh <출발 컨테이너> <루트 인증서 파일> <탐침 인자...>}; CA=${2:?}; shift 2
detect_docker
UTIL=${UTIL_IMAGE:-$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")}
insp=$("$DOCKER" inspect "$SRC" --format '{{.HostConfig.NetworkMode}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null | tr -d '\r') || { echo "출발 컨테이너가 없다: $SRC" >&2; exit 3; }
[ -n "$insp" ] || { echo "출발 컨테이너가 없다: $SRC" >&2; exit 3; }
mode=${insp%% *}; nets=${insp#* }
case "$mode" in container:*) first=$mode; nets="";; *) first=${nets%% *}; nets=${nets#"$first"}; nets=${nets# };; esac
[ -n "$first" ] || { echo "출발 컨테이너의 망을 읽지 못했다: $SRC" >&2; exit 3; }
cid=$("$DOCKER" create --network "$first" -e SSL_CERT_FILE=/ca.crt -v "$CA:/ca.crt:ro" -v "$DEPLOY_ROOT/scripts/e2e_probe.py:/e2e_probe.py:ro" --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 10001:10001 "$UTIL" python /e2e_probe.py "$@" | tr -d '\r') || exit 3
trap '"$DOCKER" rm -f "$cid" >/dev/null 2>&1' EXIT
for n in $nets; do "$DOCKER" network connect "$n" "$cid" >/dev/null 2>&1 || { echo "망 연결 실패: $n" >&2; exit 3; }; done
"$DOCKER" start -a "$cid" 2>/dev/null | tr -d '\r'; exit ${PIPESTATUS[0]}
