#!/usr/bin/env bash
# 분리 배치의 인증서·DB 경로를 실제 플레이북(ansible/site.yml, stage.yml)으로 시험한다(ADR 0060, 0061). E2E 밖, 단독.
# 가상 서버 2개 = compose 프로젝트 2개(서로 다른 Docker 망). 제품 compose.yaml 에서 아래 서비스만 뽑은 compose 로 돈다(제품 정의 그대로, 서비스 수만 줄임).
#   data 서버: step-ca, pki-root, pki-tokens, postgres, postgres-cert, postgres-reload   (실제 잠금 이미지)
#   app 서버 : release-gate(응답만 하는 대역 앱), release-gate-cert, release-gate-tls(실제 인증서 컨테이너·사이드카)
# 확인: (1) 토큰 전달 단계가 돌아 app 서버 토큰 볼륨에 release-gate.ott 가 640 으로 있다 (2) app 서버 -cert 가 extra_hosts step-ca:<호스트> + 게시 포트 9000 으로 다른 망의 step-ca 에서
#       서비스 이름 인증서를 받았다 (3) app 서버의 DSN(sslmode=verify-full)로 다른 망의 postgres 에 접속하고 pg-tls 소유자는 999 다 (4) 2회차 changed=0
# 고정 포트 9000: 인증서 발급 명령이 https://step-ca:9000 으로 고정이라 step-ca 의 게시 포트가 9000 이어야 한다(placement 점검이 강제). 이미 9000 이 쓰이면 이 시험은 실패로 알리고 멈춘다.
#   다른 시험과 동시에 돌 수 없다. 풀려면 제품 compose 의 step-ca 주소·포트를 변수로 바꿔야 한다(deploy 구조 변경, 이 시험의 범위 밖).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; ID="splitpki-$$"
PY=${DEPLOY_PY:-}; [ -n "$PY" ] || for c in "$ROOT/.venv/bin/python" "$ROOT/../../.venv/bin/python"; do [ -x "$c" ] && PY=$c && break; done
AP="$(dirname "$PY")/ansible-playbook"
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
ss -ltn 2>/dev/null | grep -q ':9000 ' && bad "호스트 포트 9000 이 이미 쓰인다(step-ca 게시 포트는 9000 고정). 다른 시험이 끝난 뒤 다시 돌린다"
T=$(mktemp -d)
trap 'rc=$?; if [ $rc -ne 0 ]; then for s in data app; do docker ps -a --filter "label=com.docker.compose.project=deploy-$ID-$s" --format "{{.Names}} {{.Status}}" >&2; for n in $(docker ps -a -q --filter "label=com.docker.compose.project=deploy-$ID-$s"); do echo "--- $(docker inspect -f "{{.Name}}" $n)" >&2; docker logs --tail 8 $n 2>&1 | cut -c1-200 >&2; done; done; tail -25 "$T/run1.log" 2>/dev/null >&2; fi; [ "${SPLIT_KEEP:-0}" = 1 ] || { for s in data app; do docker compose -p "deploy-$ID-$s" down -v --remove-orphans >/dev/null 2>&1; done; rm -rf "$T" "$ROOT/build/placement/$ID"-*; }; exit $rc' EXIT
freeport() { python3 -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])'; }
PGP=$(freeport)
HOSTADDR=$(getent hosts host.docker.internal | awk '{print $1}' | head -1); [ -n "$HOSTADDR" ] || HOSTADDR=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')
LOCK="$T/images.lock"; cp locks/images.lock "$LOCK"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK"); PGIMG=$(sed -n 's/^POSTGRES_IMAGE=//p' "$LOCK"); CAIMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK")
# 비밀: PostgreSQL 비밀(gen-secrets --db-only)과 step-ca 비밀번호. 값은 출력하지 않는다
mkdir -p "$T/secrets"; DEPLOY_NO_DOCKER=1 bash scripts/gen-secrets.sh --db-only "$T/secrets" >/dev/null
( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$T/secrets/tokens/step-ca-password" ); chmod 640 "$T/secrets/tokens/step-ca-password"
# 제품 compose 에서 서비스만 뽑는다. release-gate 는 앱만 대역(응답만 하는 파이썬)으로 바꾸고 인증서·사이드카·네트워크·sysctl·DB 비밀은 제품 정의 그대로 둔다
"$PY" - "$ROOT/compose.yaml" "$T/compose.subset.yaml" <<'PYEOF'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
keep = ["step-ca", "pki-root", "pki-tokens", "postgres", "postgres-cert", "postgres-reload", "release-gate", "release-gate-cert", "release-gate-tls"]
svc = {k: c["services"][k] for k in keep}
rg = svc["release-gate"]
for k in ("env_file", "environment", "volumes", "stop_grace_period"):
    rg.pop(k, None)
rg["image"] = "${UTIL_IMAGE}"
rg["entrypoint"] = ["python", "-c", "import http.server as h\nclass H(h.BaseHTTPRequestHandler):\n    def do_GET(s):\n        s.send_response(200); s.end_headers(); s.wfile.write(b'ok')\n    def log_message(s, *a): pass\nh.ThreadingHTTPServer(('127.0.0.1', 8080), H).serve_forever()"]
rg.pop("command", None)
rg["secrets"] = ["db-gate-dsn"]
for n, s in svc.items():
    d = s.get("depends_on")
    if isinstance(d, dict):
        s["depends_on"] = {k: v for k, v in d.items() if k in keep}
c["services"] = svc
yaml.safe_dump(c, open(sys.argv[2], "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PYEOF
cat > "$T/inv.yml" <<YML
all:
  vars:
    ansible_connection: local
    placement_scheme: https
    placement_compose: $T/compose.subset.yaml
    placement_config_dir: $ROOT/config
    placement_lock: $T/images.lock
    placement_secrets_dir: $T/secrets
    placement_probe_address: 127.0.0.1
    placement_bind_address: 0.0.0.0
    placement_ports: {step-ca: 9000, postgres: $PGP}
  hosts:
    $ID-data: {ansible_host: $HOSTADDR, placement_region: r1, placement_project: deploy-$ID-data, placement_remote_dir: $T/r/data, placement_services: [step-ca, postgres]}
    $ID-app: {ansible_host: $HOSTADDR, placement_region: r2, placement_project: deploy-$ID-app, placement_remote_dir: $T/r/app, placement_services: [release-gate]}
YML
"$PY" scripts/placement.py validate "$T/inv.yml" --compose "$T/compose.subset.yaml" >/dev/null || bad "인벤토리 점검"
ok "인벤토리 점검 통과 (step-ca·postgres 는 data 서버, release-gate 는 app 서버)"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$T/ans" ANSIBLE_HOME="$T/ansible-home" UTIL_IMAGE="$UTIL"
timeout 600 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run1.log" 2>&1 || bad "플레이북 실패"
ok "플레이북 1회차 완료"
A=deploy-$ID-app; D=deploy-$ID-data
grep -a "토큰 볼륨에 쓰기" -A1 "$T/run1.log" | grep -aq "changed: \[$ID-app\]" || bad "토큰 전달 단계가 app 서버에서 돌지 않았다"; ok "(1) 토큰 전달 단계가 실제로 돌았다"
M=$(docker run --rm --network none -v ${A}_pki-tokens:/t:ro "$UTIL" sh -c 'stat -c %a:%u /t/release-gate.ott'); [ "$M" = 640:1000 ] || bad "app 서버의 토큰 파일 권한/소유자 $M"; ok "(1) app 서버 토큰 파일 640, 소유자 1000"
docker run --rm --network none -v ${A}_pki-tokens:/t:ro -v ${A}_pki-root:/r:ro "$UTIL" sh -c 'ls /t /r' | grep -Eq 'password|\.key|ca\.json' && bad "app 서버에 프로비저너 비밀 또는 CA 키가 있다"; ok "(1) app 서버에는 프로비저너 비밀·CA 키가 없다"
grep -q 'step-ca:' "$T/r/app/compose.placement.yaml" && ok "(2) app 서버 override 에 extra_hosts step-ca:<호스트>" || bad "extra_hosts step-ca 없음"
[ "$(docker inspect -f '{{.State.Health.Status}}' $A-release-gate-cert-1)" = healthy ] || bad "release-gate-cert 가 healthy 가 아니다"
S=$(docker run --rm --network none -v ${A}_certs-release-gate:/c:ro "$UTIL" cat /c/tls.crt | openssl x509 -noout -subject -issuer 2>/dev/null)
case "$S" in *"CN = release-gate"*|*"CN=release-gate"*) ok "(2) app 서버 -cert 가 다른 망의 step-ca 에서 서비스 이름(release-gate) 인증서를 받았다";; *) bad "인증서 주체: $S";; esac
[ "$(docker inspect -f '{{.State.Health.Status}}' $A-release-gate-tls-1)" = healthy ] && ok "(2) 사이드카가 그 인증서로 443 을 연다(healthy)" || bad "사이드카가 healthy 가 아니다"
O=$(docker run --rm --network none -v ${D}_pg-tls:/p:ro "$UTIL" stat -c %u /p/server.key); [ "$O" = 999 ] || bad "pg-tls 의 server.key 소유자 $O"; ok "(3) postgres-cert 의 pg-tls 소유자 999"
DSN="$T/r/app/secrets/tokens/db-gate-dsn"; grep -q "@postgres:$PGP/" "$DSN" && grep -q 'sslmode=verify-full' "$DSN" || bad "app 서버 DSN 의 호스트·sslmode"
ok "(3) app 서버 DSN = postgres:$PGP, sslmode=verify-full"
R=$(docker run --rm --network ${A}_serving --add-host postgres:$HOSTADDR -v ${A}_pki-root:/etc/openit/pki:ro -v "$DSN:/dsn:ro" "$PGIMG" sh -c 'psql "$(cat /dsn)" -qAt -c "select 1"' 2>&1) || { echo "$R" | tail -3 | cut -c1-200 >&2; bad "app 서버 DSN 으로 다른 망의 postgres 에 verify-full 접속 실패"; }
[ "$R" = 1 ] && ok "(3) 다른 망의 postgres 에 sslmode=verify-full 로 접속했다(서버 인증서 이름 postgres, step-ca 루트 검증)"
R=$(docker run --rm --network ${A}_serving --add-host postgres:$HOSTADDR -v ${A}_pki-root:/etc/openit/pki:ro -v "$DSN:/dsn:ro" "$PGIMG" sh -c 'psql "$(sed "s/verify-full/disable/" /dsn)" -qAt -c "select 1"' 2>&1) && bad "TLS 없는 접속이 통과했다" || ok "(3) TLS 없는 접속은 거부된다(hostssl 만)"
timeout 600 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run2.log" 2>&1 || { tail -25 "$T/run2.log" >&2; bad "플레이북 2회차 실패"; }
if grep -aE '^[a-z0-9-]+ +: ok=' "$T/run2.log" | grep -v 'changed=0 '; then bad "2회차에 바뀐 것이 있다(멱등 아님)"; fi
ok "(4) 플레이북 2회차 changed=0"
echo "PASS: 분리 배치 인증서·DB 경로 시험"
