#!/usr/bin/env bash
# 분리 배치 시험(E2E 밖, 단독, ADR 0060): 이 PC 한 대에서 "가상 서버 3개" = compose 프로젝트 3개(서로 다른 Docker 네트워크)에 서비스를 3묶음으로 나눠 같은 플레이북(ansible/site.yml)으로 띄운다.
# 확인: (1) 묶음마다 /healthz  (2) 묶음 사이 호출 1건씩 성공(survey-service -> release-gate, release-gate -> question-authoring): 호스트 게시 포트로만  (3) 같은 네트워크가 아님(이름으로 닿지 않는다)
#       (4) 인벤토리 점검이 잘못된 배치를 거부  (5) 플레이북을 다시 돌리면 바뀐 것이 없다(멱등)
# 대역 서비스를 쓴다(test/split/): 실제 이미지는 레지스트리 digest 로만 받는다. 이 시험은 배치를 본다.
# 변수: SPLIT_SCHEME(기본 http. TLS 가 합쳐진 뒤 https 로 돌리려면 STUB_CA 도 준다), SPLIT_KEEP=1 이면 끝나도 정리하지 않는다. 고정 포트를 쓰지 않는다(빈 포트를 고른다).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; SCHEME=${SPLIT_SCHEME:-http}; ID="split-$$"
PY=${DEPLOY_PY:-}; [ -n "$PY" ] || for c in "$ROOT/.venv/bin/python" "$ROOT/../../.venv/bin/python"; do [ -x "$c" ] && PY=$c && break; done
AP="$(dirname "$PY")/ansible-playbook"; [ -x "$AP" ] || { echo "FAIL: ansible-playbook 이 없다: .venv/bin/pip install -r requirements-deploy-tools.txt" >&2; exit 1; }
T=$(mktemp -d); trap 'rc=$?; if [ $rc -ne 0 ]; then for s in a b c; do docker ps -a --filter "label=com.docker.compose.project=deploy-$ID-$s" --format "{{.Names}} {{.Status}}" >&2; for n in $(docker ps -a -q --filter "label=com.docker.compose.project=deploy-$ID-$s"); do docker logs --tail 5 $n >&2 2>&1 || true; done; done; fi; [ "${SPLIT_KEEP:-0}" = 1 ] || { for s in a b c; do docker compose -p "deploy-$ID-$s" down -v --remove-orphans >/dev/null 2>&1 || true; done; rm -rf "$T" "$ROOT/build/placement/split-$$"-* 2>/dev/null; }; exit $rc' EXIT
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
freeport() { python3 -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])'; }
PORT_GATE=$(freeport); PORT_QA=$(freeport)
mkdir -p "$T/secrets/tokens" "$T/r" ; echo 'UTIL_IMAGE=python:3.12-slim' > "$T/images.lock"
printf 'postgresql://survey:x@postgres:5432/survey\n' > "$T/secrets/tokens/db-survey-dsn"
# 서버 주소: 컨테이너에서 이 PC 를 부르는 이름(host-gateway). 서버가 바뀌어도 이 값만 인벤토리에서 바뀐다
HOSTADDR=host.docker.internal
inv() { # inv <파일> <a의 서비스> <b> <c>
cat > "$1" <<YML
all:
  vars:
    ansible_connection: local
    placement_scheme: $SCHEME
    placement_publish_bind: 0.0.0.0
    placement_ports: {release-gate: $PORT_GATE, question-authoring: $PORT_QA}
    placement_compose: $ROOT/test/split/compose.split.yaml
    placement_config_dir: $ROOT/test/split/config
    placement_lock: $T/images.lock
    placement_secrets_dir: $T/secrets
  hosts:
    $ID-a: {ansible_host: $HOSTADDR, placement_region: r1, placement_project: deploy-$ID-a, placement_remote_dir: $T/r/a, placement_services: $2}
    $ID-b: {ansible_host: $HOSTADDR, placement_region: r2, placement_project: deploy-$ID-b, placement_remote_dir: $T/r/b, placement_services: $3}
    $ID-c: {ansible_host: $HOSTADDR, placement_region: r3, placement_project: deploy-$ID-c, placement_remote_dir: $T/r/c, placement_services: $4}
YML
}
# (4) 잘못된 배치는 서버에 닿기 전에 거부된다
inv "$T/bad-dup.yml" "[postgres, keycloak, survey-service, release-gate]" "[release-gate, gateway]" "[question-authoring]"
! "$PY" scripts/placement.py validate "$T/bad-dup.yml" --compose test/split/compose.split.yaml 2>"$T/e" || bad "한 서비스가 두 서버에 있는 배치를 통과시켰다"; grep -q "두 곳" "$T/e" && ok "중복 배치 거부"
inv "$T/bad-found.yml" "[postgres, survey-service]" "[release-gate, gateway]" "[question-authoring]"
! "$PY" scripts/placement.py validate "$T/bad-found.yml" --compose test/split/compose.split.yaml 2>"$T/e" || bad "기반 요소(keycloak)가 빠진 배치를 통과시켰다"; grep -q "keycloak" "$T/e" && ok "기반 요소 누락 거부"
inv "$T/bad-name.yml" "[postgres, keycloak, survey-service, nonesuch]" "[release-gate, gateway]" "[question-authoring]"
! "$PY" scripts/placement.py validate "$T/bad-name.yml" --compose test/split/compose.split.yaml 2>"$T/e" || bad "없는 서비스 이름을 통과시켰다"; grep -q "nonesuch" "$T/e" && ok "없는 서비스 이름 거부"
inv "$T/bad-db.yml" "[postgres, keycloak]" "[release-gate, gateway, survey-service]" "[question-authoring]"
! "$PY" scripts/placement.py validate "$T/bad-db.yml" --compose test/split/compose.split.yaml 2>"$T/e" || bad "DB 비밀을 쓰는 서비스가 postgres 와 떨어진 배치를 통과시켰다"; grep -q "postgres 와 같은 서버" "$T/e" && ok "DB 비밀 서비스의 postgres 분리 거부"
# (3) 서버 1개 배치는 기존 up.sh 와 같다: 예시 인벤토리(서버 1개)의 override 는 비어 있고 모든 서비스가 한 단계 흐름으로 그 서버에 간다
"$PY" scripts/placement.py render ansible/inventory.example.yml --host core-1 --out "$T/one" >/dev/null
grep -qx 'services: {}' "$T/one/compose.placement.yaml" || bad "서버 1개 배치의 override 가 비어 있지 않다"; ok "서버 1개 배치 = 기존 동작(override 없음)"
# 3묶음
inv "$T/inv.yml" "[postgres, keycloak, survey-service]" "[release-gate, gateway]" "[question-authoring]"
"$PY" scripts/placement.py validate "$T/inv.yml" --compose test/split/compose.split.yaml >/dev/null && ok "인벤토리 점검 통과"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$T/ans" ANSIBLE_HOME="$T/ansible-home"
timeout 400 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run1.log" 2>&1 || { tail -30 "$T/run1.log" >&2; bad "플레이북 실패"; }
ok "플레이북 1회차 완료"
ex() { docker exec "deploy-$ID-$1-$2-1" python -c "$3"; } # ex <서버> <서비스> <파이썬 식>
H="import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status)"
for pair in a:postgres a:keycloak a:survey-service b:release-gate b:gateway c:question-authoring; do
  [ "$(ex "${pair%%:*}" "${pair#*:}" "$H")" = 200 ] || bad "${pair#*:} 의 /healthz"; done; ok "세 묶음의 /healthz"
C="import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/call?env=%s',timeout=8).read().decode())"
r=$(ex a survey-service "${C/\%s/SURVEY_RELEASE_READER_URL}"); [ "${r##* }" = 200 ] || bad "survey-service -> release-gate: $r"; ok "묶음 사이 호출 survey-service -> release-gate ($r)"
r=$(ex b release-gate "${C/\%s/GATE_I1_URL}"); [ "${r##* }" = 200 ] || bad "release-gate -> question-authoring: $r"; ok "묶음 사이 호출 release-gate -> question-authoring ($r)"
case "$r" in "$SCHEME://$HOSTADDR:$PORT_QA/"*) ok "상대 주소가 인벤토리에서 계산됨($SCHEME, 서버 주소, 게시 포트)";; *) bad "주소 계산: $r";; esac
# (3) 서로 다른 네트워크: 서비스 이름으로는 닿지 않는다
N="import socket
try:
    socket.getaddrinfo('release-gate',8080); print('resolved')
except OSError: print('unreachable')"
[ "$(ex a survey-service "$N")" = unreachable ] || bad "survey-service 가 이름으로 release-gate 를 찾았다(같은 네트워크)"; ok "묶음이 서로 다른 네트워크(이름으로 닿지 않음)"
[ "$(docker network ls --filter "name=deploy-$ID-" --format '{{.Name}}' | sort -u | wc -l)" -ge 3 ] || bad "네트워크가 3개 미만"; ok "Docker 네트워크 3개"
# 비밀 권한 640
M=$(stat -c %a "$T/r/a/secrets/tokens/db-survey-dsn"); [ "$M" = 640 ] || bad "비밀 파일 권한 $M"; ok "비밀 파일 640"
[ ! -e "$T/r/b/secrets/tokens/db-survey-dsn" ] || bad "다른 서버의 비밀이 배포됐다"; ok "서버는 자기 몫의 비밀만 받는다"
# (5) 멱등
timeout 400 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run2.log" 2>&1 || { tail -30 "$T/run2.log" >&2; bad "플레이북 2회차 실패"; }
if grep -E '^[a-z0-9-]+ +: ok=' "$T/run2.log" | grep -v 'changed=0 ' ; then bad "2회차에 바뀐 것이 있다(멱등 아님)"; fi; ok "플레이북 2회차 changed=0 (멱등)"
echo "PASS: 분리 배치 시험 (scheme=$SCHEME)"
