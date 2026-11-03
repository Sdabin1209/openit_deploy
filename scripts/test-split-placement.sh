#!/usr/bin/env bash
# 분리 배치 시험(E2E 밖, 단독, ADR 0060): 이 PC 한 대에서 "가상 서버 3개" = compose 프로젝트 3개(서로 다른 Docker 네트워크)에 서비스를 3묶음으로 나눠 같은 플레이북(ansible/site.yml)으로 띄운다.
# 확인: (1) 묶음마다 /healthz  (2) 묶음 사이 호출 1건씩 성공(survey-service -> release-gate, release-gate -> question-authoring): 호스트 게시 포트로만  (3) 같은 네트워크가 아님(이름으로 닿지 않는다)
#       (4) 인벤토리 점검이 잘못된 배치를 거부  (5) 플레이북을 다시 돌리면 바뀐 것이 없다(멱등)
# 대역 서비스를 쓴다(test/split/): 실제 이미지는 레지스트리 digest 로만 받는다. 이 시험은 배치를 본다.
# 변수: SPLIT_SCHEME(기본 http. TLS 가 합쳐진 뒤 https 로 돌리려면 인증서 준비 후 STUB_CA 도 준다), SPLIT_IMAGE(대역 대신 쓸 실제 이미지 참조, 파이썬이 든 이미지), SPLIT_KEEP=1 이면 정리하지 않는다. 고정 포트를 쓰지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; SCHEME=${SPLIT_SCHEME:-http}; ID="split-$$"
PY=${DEPLOY_PY:-}; [ -n "$PY" ] || for c in "$ROOT/.venv/bin/python" "$ROOT/../../.venv/bin/python"; do [ -x "$c" ] && PY=$c && break; done
AP="$(dirname "$PY")/ansible-playbook"; [ -x "$AP" ] || { echo "FAIL: ansible-playbook 이 없다: .venv/bin/pip install -r requirements-deploy-tools.txt" >&2; exit 1; }
T=$(mktemp -d); trap 'rc=$?; if [ $rc -ne 0 ]; then for s in a b c; do docker ps -a --filter "label=com.docker.compose.project=deploy-$ID-$s" --format "{{.Names}} {{.Status}}" >&2; for n in $(docker ps -a -q --filter "label=com.docker.compose.project=deploy-$ID-$s"); do docker logs --tail 5 $n >&2 2>&1 || true; done; done; fi; [ "${SPLIT_KEEP:-0}" = 1 ] || { for s in a b c; do docker compose -p "deploy-$ID-$s" down -v --remove-orphans >/dev/null 2>&1 || true; done; rm -rf "$T" "$ROOT/build/placement/split-$$"-* 2>/dev/null; }; exit $rc' EXIT
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
freeport() { python3 -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])'; }
PORT_GATE=$(freeport); PORT_QA=$(freeport); PORT_PG=$(freeport)
mkdir -p "$T/secrets/tokens" "$T/r" ; { echo 'UTIL_IMAGE=python:3.12-slim'; [ -z "${SPLIT_IMAGE:-}" ] || echo "SPLIT_IMAGE=$SPLIT_IMAGE"; } > "$T/images.lock"   # 실제 이미지 참조는 잠금 파일(--env-file)로 준다
printf 'postgresql://survey:x@postgres:5432/survey\n' > "$T/secrets/tokens/db-survey-dsn"
# 서버 주소: 컨테이너에서 이 PC 를 부르는 이름(host-gateway). 서버가 바뀌어도 이 값만 인벤토리에서 바뀐다
HOSTADDR=host.docker.internal
PORTS_YAML="{postgres: $PORT_PG, release-gate: $PORT_GATE, question-authoring: $PORT_QA}"
inv() { # inv <파일> <a의 서비스> <b> <c>
cat > "$1" <<YML
all:
  vars:
    ansible_connection: local
    placement_scheme: $SCHEME
    placement_check_contracts: false   # 대역 서비스는 영역 계약이 없다(실제 구성은 기본 true)
    placement_probe_address: 127.0.0.1 # 지휘 기계(이 PC)에서 /readyz 를 보는 주소
    placement_bind_address: 0.0.0.0    # 시험 PC 한 대라 모든 주소(실제 구성은 서버 사이 망의 사설 주소)
    placement_ports: $PORTS_YAML
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
A="[postgres, keycloak, release-gate]"; B="[survey-service, gateway]"; C="[question-authoring]"
reject() { # reject <이름> <기대 메시지> <a> <b> <c>
  inv "$T/bad-$1.yml" "$3" "$4" "$5"
  ! "$PY" scripts/placement.py validate "$T/bad-$1.yml" --compose test/split/compose.split.yaml 2>"$T/e" || bad "잘못된 배치($1)를 통과시켰다"
  grep -q "$2" "$T/e" || { cat "$T/e" >&2; bad "거부 사유($1)에 '$2' 가 없다"; }; ok "거부: $1"
}
reject dup "두 곳" "[postgres, keycloak, release-gate, survey-service]" "[release-gate, gateway]" "$C"
reject found "keycloak" "[postgres, release-gate]" "[survey-service, gateway]" "$C"
reject name "nonesuch" "[postgres, keycloak, release-gate, nonesuch]" "$B" "$C"
SAVE=$PORTS_YAML; PORTS_YAML="{postgres: $PORT_PG, question-authoring: $PORT_QA}"; reject noport "release-gate.*placement_ports" "$A" "$B" "$C"
PORTS_YAML="{postgres: $PORT_PG, release-gate: $PORT_GATE, question-authoring: $PORT_QA, gateway: 19999}"; reject extraport "gateway.*필요 없는" "$A" "$B" "$C"
PORTS_YAML=$SAVE
# (3) 서버 1개 배치는 기존 up.sh 와 같다: 예시 인벤토리(서버 1개)의 override 는 비어 있다
"$PY" scripts/placement.py render ansible/inventory.example.yml --host core-1 --out "$T/one" >/dev/null
grep -qx 'services: {}' "$T/one/compose.placement.yaml" || bad "서버 1개 배치의 override 가 비어 있지 않다"; ok "서버 1개 배치 = 기존 동작(override 없음)"
"$PY" scripts/placement.py validate ansible/inventory.multi.example.yml >/dev/null && ok "서버 2개 예시 인벤토리(게시 포트 명시) 통과"
# 3묶음: postgres 와 survey-service 가 다른 서버, 내부 전용 네트워크의 postgres·question-authoring 을 다른 서버가 부른다
inv "$T/inv.yml" "$A" "$B" "$C"
"$PY" scripts/placement.py validate "$T/inv.yml" --compose test/split/compose.split.yaml >/dev/null && ok "인벤토리 점검 통과"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$T/ans" ANSIBLE_HOME="$T/ansible-home"
timeout 500 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run1.log" 2>&1 || { tail -30 "$T/run1.log" >&2; bad "플레이북 실패"; }
ok "플레이북 1회차 완료"
# 기동 직후 첫 서버 사이 호출은 느릴 수 있다(실제 이미지에서 측정됨: 첫 호출이 대역 서비스의 3초 제한에 걸림). 성공할 때까지 최대 5번
exr() { local i o; for i in 1 2 3 4 5; do o=$(ex "$@") && [ "${o##* }" = 200 ] && { echo "$o"; return 0; }; sleep 2; done; echo "$o"; }
ex() { docker exec "deploy-$ID-$1-$2-1" python -c "$3"; } # ex <서버> <서비스> <파이썬 식>
H="import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status)"
for pair in a:postgres a:keycloak a:release-gate b:survey-service b:gateway c:question-authoring; do
  [ "$(ex "${pair%%:*}" "${pair#*:}" "$H")" = 200 ] || bad "${pair#*:} 의 /healthz"; done; ok "세 묶음의 /healthz"
C1="import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/call?env=%s',timeout=8).read().decode())"
r=$(exr b survey-service "${C1/\%s/SURVEY_RELEASE_READER_URL}"); [ "${r##* }" = 200 ] || bad "survey-service -> release-gate: $r"; ok "묶음 사이 호출 survey-service -> release-gate ($r)"
case "$r" in "$SCHEME://$HOSTADDR:$PORT_GATE/"*) ok "상대 주소가 인벤토리에서 계산됨($SCHEME, 서버 주소, 게시 포트)";; *) bad "주소 계산: $r";; esac
r=$(exr a release-gate "${C1/\%s/GATE_I1_URL}"); [ "${r##* }" = 200 ] || bad "release-gate -> question-authoring: $r"; ok "묶음 사이 호출 release-gate -> question-authoring, 내부 전용 네트워크의 서비스를 게시 포트로 ($r)"
# 다른 서버의 postgres: DSN 의 호스트가 인벤토리 값으로 계산되고, 그 게시 포트에 닿는다
DSN=$(cat "$T/r/b/secrets/tokens/db-survey-dsn")
case "$DSN" in *"@$HOSTADDR:$PORT_PG/survey"*) ok "survey-service 의 DSN 호스트 = postgres 서버 주소와 게시 포트";; *) bad "DSN 호스트 계산";; esac
case "$SCHEME" in https) case "$DSN" in *sslmode=verify-full*sslrootcert=*) ok "DSN sslmode=verify-full, sslrootcert";; *) bad "DSN 에 sslmode=verify-full 이 없다";; esac;; *) case "$DSN" in *sslmode*) bad "http 시험인데 DSN 에 sslmode";; esac;; esac
S="import socket;socket.create_connection(('$HOSTADDR',$PORT_PG),timeout=5);print('connected')"
[ "$(ex b survey-service "$S")" = connected ] || bad "survey-service 가 다른 서버의 postgres 게시 포트에 닿지 않는다"; ok "survey-service -> 다른 서버의 postgres 연결(게시 포트)"
# 서버를 넘는 기동 순서: postgres < (release-gate, question-authoring) < survey-service < gateway
st() { docker inspect -f '{{.State.StartedAt}}' "deploy-$ID-$1-$2-1"; }
P1=$(st a postgres); G1=$(st a release-gate); Q1=$(st c question-authoring); S1=$(st b survey-service); W1=$(st b gateway)
[[ "$P1" < "$G1" && "$P1" < "$Q1" && "$G1" < "$S1" && "$Q1" < "$S1" && "$S1" < "$W1" ]] || bad "기동 순서가 단계를 따르지 않는다: pg=$P1 gate=$G1 qa=$Q1 survey=$S1 gw=$W1"; ok "서버를 넘는 기동 순서(postgres < gate·qa < survey < gateway)"
grep -q "/readyz" "$T/run1.log" && ok "게시된 서비스의 /readyz 를 지휘 기계가 기다림"
# (3) 서로 다른 네트워크: 서비스 이름으로는 닿지 않는다
N="import socket
try:
    socket.getaddrinfo('release-gate',8080); print('resolved')
except OSError: print('unreachable')"
[ "$(ex b survey-service "$N")" = unreachable ] || bad "survey-service 가 이름으로 release-gate 를 찾았다(같은 네트워크)"; ok "묶음이 서로 다른 네트워크(이름으로 닿지 않음)"
[ "$(docker network ls --filter "name=deploy-$ID-" --format '{{.Name}}' | sed 's/_.*//' | sort -u | wc -l)" -ge 3 ] || bad "네트워크가 3개 미만"; ok "Docker 네트워크 3개 이상"
# 비밀 권한 640, 다른 서버 몫은 배포되지 않는다
M=$(stat -c %a "$T/r/b/secrets/tokens/db-survey-dsn"); [ "$M" = 640 ] || bad "비밀 파일 권한 $M"; ok "비밀 파일 640"
[ ! -e "$T/r/a/secrets/tokens/db-survey-dsn" ] || bad "다른 서버의 비밀이 배포됐다"; ok "서버는 자기 몫의 비밀만 받는다"
# (5) 멱등
timeout 500 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run2.log" 2>&1 || { tail -30 "$T/run2.log" >&2; bad "플레이북 2회차 실패"; }
if grep -E '^[a-z0-9-]+ +: ok=' "$T/run2.log" | grep -v 'changed=0 ' ; then bad "2회차에 바뀐 것이 있다(멱등 아님)"; fi; ok "플레이북 2회차 changed=0 (멱등)"
echo "PASS: 분리 배치 시험 (scheme=$SCHEME, 이미지=${SPLIT_IMAGE:-python:3.12-slim})"
