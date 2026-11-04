#!/usr/bin/env bash
# 분리 배치의 인증서·DB 경로를 실제 플레이북(ansible/site.yml, stage.yml)으로 시험한다(ADR 0060, 0061). E2E 밖, 단독.
# 가상 서버 2개 = compose 프로젝트 2개(서로 다른 Docker 망). 제품 compose.yaml 에서 아래 서비스만 뽑은 compose 로 돈다(제품 정의 그대로, 서비스 수만 줄임).
#   data 서버: step-ca, pki-root, pki-tokens, release-gate-db, release-gate-db-cert, release-gate-db-reload   (실제 잠금 이미지)
#   app 서버 : release-gate(응답만 하는 대역 앱), release-gate-cert, release-gate-gw(실제 인증서 컨테이너·platform 영역 게이트웨이 이미지)
# 확인: (1) 토큰 전달 단계가 돌아 app 서버 토큰 볼륨에 release-gate.ott 가 640 으로 있다 (2) app 서버 -cert 가 extra_hosts step-ca:<호스트> + 게시 포트(STEP_CA_PORT)로 다른 망의 step-ca 에서
#       서비스 이름 인증서를 받았다 (3) app 서버의 DSN(sslmode=verify-full)로 다른 망의 release-gate-db 에 접속하고 pg-tls 소유자는 999 다 (4) 2회차 changed=0
# 고정 포트가 없다: step-ca 와 release-gate-db 의 게시 포트는 빈 포트를 골라 인벤토리에 넣는다(step-ca 는 STEP_CA_PORT 로 안팎 같은 값). 다른 시험과 동시에 돌 수 있다.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; ID="splitpki-$$"
PY=${DEPLOY_PY:-}; [ -n "$PY" ] || for c in "$ROOT/.venv/bin/python" "$ROOT/../../.venv/bin/python"; do [ -x "$c" ] && PY=$c && break; done
AP="$(dirname "$PY")/ansible-playbook"
# 실패한 task 의 이름·대상·모듈만 보인다(no_log 로 가려진 값·비밀은 보이지 않는다): 묶음에서만 나는 실패의 원인 파악용
failed_tasks() { awk '/^TASK \[/{t=$0} /^fatal:/{print "  실패 task: " t " / " substr($0, 1, 90)}' "$1" >&2; }
failed_stderr() { python3 - "$1" >&2 <<'PY'   # 실패한 명령의 오류 출력 끝(compose 의 기동 진행 줄은 뺀다). no_log 로 가려진 task 는 가려진 채로 둔다
import json, re, sys
for l in open(sys.argv[1], encoding="utf-8", errors="replace"):
    if l.startswith("fatal:") and "=> " in l:
        try: d = json.loads(l.split("=> ", 1)[1])
        except ValueError: continue
        if "censored" in d: print("  (no_log 로 가려진 task)"); continue
        err = [x for x in (d.get("stderr") or "").splitlines() if not re.search(r"Network|Volume|Creating|Created|Starting|Started|Waiting|Running|Healthy", x)]
        print("  오류:", " | ".join(err[-4:])[:600])
PY
}
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
T=$(mktemp -d)
trap 'rc=$?; if [ $rc -ne 0 ]; then for s in data app; do docker ps -a --filter "label=com.docker.compose.project=deploy-$ID-$s" --format "{{.Names}} {{.Status}}" >&2; for n in $(docker ps -a -q --filter "label=com.docker.compose.project=deploy-$ID-$s"); do echo "--- $(docker inspect -f "{{.Name}}" $n)" >&2; docker logs --tail 8 $n 2>&1 | cut -c1-200 >&2; done; done; tail -25 "$T/run1.log" 2>/dev/null >&2; fi; [ "${SPLIT_KEEP:-0}" = 1 ] || { for s in data app; do docker compose -p "deploy-$ID-$s" down -v --remove-orphans >/dev/null 2>&1; done; rm -rf "$T" "$ROOT/build/placement/$ID"-* "$ROOT/build/placement.lock"; }; exit $rc' EXIT
freeport() { python3 -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])'; }
PGP=$(freeport); SCP=$(freeport); RGP=$(freeport)
if ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)443$"; then RGP=443; fi   # 다른 서버의 추론 서버는 https://release-gate(443)로 온다(RUNTIME R1.5): 게시 포트가 443 인 실제 경로를 본다. 호스트의 443 이 사용 중이면 임의 포트로 돌고 아래 443 단언은 SKIP 으로 센다   # step-ca 포트도 빈 포트: 안팎이 같은 값(STEP_CA_PORT)이라 플레이북이 서버마다 내보낸다
HOSTADDR=$(getent hosts host.docker.internal | awk '{print $1}' | head -1); [ -n "$HOSTADDR" ] || HOSTADDR=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')
LOCK="$T/images.lock"; cp locks/images.lock "$LOCK"; export DEPLOY_LOCK="$LOCK"   # 왜: 잠금 파일을 시험이 스스로 정한다(밖에서 내보낸 DEPLOY_LOCK 이 있으면 그 파일을 읽어 플레이북이 실패했다, E2E 사전 점검에서 확인)
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK"); PGIMG=$(sed -n 's/^POSTGRES_IMAGE=//p' "$LOCK"); CAIMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK")
# 비밀: PostgreSQL 비밀(gen-secrets --db-only)과 step-ca 비밀번호. 값은 출력하지 않는다
mkdir -p "$T/secrets"; DEPLOY_NO_DOCKER=1 bash scripts/gen-secrets.sh --db-only "$T/secrets" >/dev/null
( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$T/secrets/tokens/step-ca-password" ); chmod 640 "$T/secrets/tokens/step-ca-password"
# 제품 compose 에서 서비스만 뽑는다. release-gate 는 앱만 대역(응답만 하는 파이썬)으로 바꾸고 인증서·사이드카·네트워크·sysctl·DB 비밀은 제품 정의 그대로 둔다
mkdir -p "$T/gw"; echo '{"service":"release-gate","routes":[{"paths":["/"],"methods":["GET"],"auth":{"kind":"none"},"user_header":"strip"}],"egress":[]}' > "$T/gw/exposure.json"
"$PY" - "$ROOT/compose.yaml" "$T/compose.subset.yaml" "$ROOT/build/images.env" "$T/gw/exposure.json" <<'PYEOF'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
keep = ["step-ca", "pki-root", "pki-tokens", "release-gate-db", "release-gate-db-cert", "release-gate-db-reload", "release-gate-net", "release-gate", "release-gate-cert", "release-gate-gw", "certs-perms"]
svc = {k: c["services"][k] for k in keep}
rg = svc["release-gate"]
for k in ("env_file", "environment", "volumes", "stop_grace_period"):
    rg.pop(k, None)
rg["image"] = "${UTIL_IMAGE}"
# platform 이미지는 deploy 가 빌드한 로컬 이미지(build/images.env)로 바꾼다(이 시험은 레지스트리를 쓰지 않는다). 영역 게이트웨이의 Exposure 는 시험 파일 하나다
imgs = {l.split()[0]: l.split()[1] for l in open(sys.argv[3], encoding="utf-8") if l.strip()}
for k, v in svc.items():
    if "openit/step-ca@" in str(v.get("image", "")): v["image"] = imgs["step-ca"]
    if "openit/area-gateway@" in str(v.get("image", "")): v["image"] = imgs["area-gateway"]
for v in svc["release-gate-gw"]["volumes"]:
    if isinstance(v, dict) and v.get("target") == "/etc/openit/exposure.json": v["source"] = sys.argv[4]
rg["entrypoint"] = ["python", "-c", "import http.server as h\nclass H(h.BaseHTTPRequestHandler):\n    def do_GET(s):\n        s.send_response(200); s.end_headers(); s.wfile.write(b'ok')\n    def log_message(s, *a): pass\nh.ThreadingHTTPServer(('127.0.0.1', 8080), H).serve_forever()"]
rg.pop("command", None)
rg["secrets"] = ["db-gate-dsn"]
for n, s in svc.items():
    d = s.get("depends_on")
    if isinstance(d, dict):
        s["depends_on"] = {k: v for k, v in d.items() if k in keep}
# 다른 서버의 호출자(대역): 계약 클라이언트처럼 https://release-gate 를 SSL_CERT_FILE 루트로 부른다. 주소 설정은 제품 config/survey.env 의 값 그대로(이름만)다
svc["survey-service"] = {"image": "${UTIL_IMAGE}", "restart": "no", "networks": ["serving"],
    "env_file": ["${CONFIG_DIR:-./config}/survey.env"], "environment": {"SSL_CERT_FILE": "/etc/openit/pki/root_ca.crt"},
    "volumes": ["pki-root:/etc/openit/pki:ro"],
    "entrypoint": ["python", "-c", "import http.server as h, os, urllib.request as u\nclass H(h.BaseHTTPRequestHandler):\n    def do_GET(s):\n        url = os.environ['SURVEY_RELEASE_READER_URL'] + '/'\n        try:\n            r = u.urlopen(url, timeout=4); out = '%d %s %s' % (r.status, url, r.read().decode()[:20])\n        except u.HTTPError as e:\n            out = '%d %s' % (e.code, url)\n        except Exception as e:\n            out = 'ERR %s %s' % (url, type(e).__name__)\n        s.send_response(200); s.end_headers(); s.wfile.write(out.encode())\n    def log_message(s, *a): pass\nh.ThreadingHTTPServer(('127.0.0.1', 8080), H).serve_forever()"],
    "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/',timeout=8)"], "interval": "3s", "timeout": "9s", "retries": 10}}
c["services"] = svc
for k in [k for k in c if k.startswith("x-")]: del c[k]   # 확장 조각(앵커 원본)은 이미 풀려 있다. 남기면 쓰지 않는 조각의 변수까지 해석한다
yaml.safe_dump(c, open(sys.argv[2], "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PYEOF
ln -s "$ROOT/config" "$T/config"   # 배치 도구가 compose 옆의 config/*.env 에서 호출 설정을 읽는다
cat > "$T/inv.yml" <<YML
all:
  vars:
    ansible_connection: local
    placement_scheme: https
    placement_compose: $T/compose.subset.yaml
    placement_config_dir: $ROOT/config
    placement_lock: $T/images.lock
    placement_no_lock: true
    placement_no_log: ${PLACEMENT_NO_LOG:-true}   # 왜: 이 시험은 여러 번 동시에 돌 수 있다. 배치 잠금 자체는 test_placement_ops.py 가 본다(R10.12)
    placement_secrets_dir: $T/secrets
    placement_probe_address: 127.0.0.1
    placement_bind_address: 0.0.0.0
    placement_ports: {step-ca: $SCP, release-gate-db: $PGP, release-gate: $RGP}
  hosts:
    $ID-data: {ansible_host: $HOSTADDR, placement_region: r1, placement_project: deploy-$ID-data, placement_remote_dir: $T/r/data, placement_services: [step-ca, release-gate-db, survey-service]}
    $ID-app: {ansible_host: $HOSTADDR, placement_region: r2, placement_project: deploy-$ID-app, placement_remote_dir: $T/r/app, placement_services: [release-gate]}
YML
"$PY" scripts/placement.py validate "$T/inv.yml" --compose "$T/compose.subset.yaml" >/dev/null || bad "인벤토리 점검"
ok "인벤토리 점검 통과 (step-ca·release-gate-db 는 data 서버, release-gate 는 app 서버)"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$T/ans" ANSIBLE_HOME="$T/ansible-home" UTIL_IMAGE="$UTIL"
timeout 600 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run1.log" 2>&1 || { grep -a -A12 -m2 "^fatal" "$T/run1.log" | cut -c1-8000 >&2; tail -15 "$T/run1.log" >&2; failed_tasks "$T/run1.log"; failed_stderr "$T/run1.log"; bad "플레이북 실패"; }
ok "플레이북 1회차 완료"
A=deploy-$ID-app; D=deploy-$ID-data
grep -a "토큰 볼륨에 쓰기" -A3 "$T/run1.log" | grep -aq "changed: .*$ID-app" || bad "토큰 전달 단계가 app 서버에서 돌지 않았다"; ok "(1) 토큰 전달 단계가 실제로 돌았다"
M=$(docker run --rm --network none -v ${A}_pki-tokens:/t:ro "$UTIL" sh -c 'stat -c %a:%u /t/release-gate.ott'); [ "$M" = 640:1000 ] || bad "app 서버의 토큰 파일 권한/소유자 $M"; ok "(1) app 서버 토큰 파일 640, 소유자 1000"
docker run --rm --network none -v ${A}_pki-tokens:/t:ro -v ${A}_pki-root:/r:ro "$UTIL" sh -c 'ls /t /r' | grep -Eq 'password|\.key|ca\.json' && bad "app 서버에 프로비저너 비밀 또는 CA 키가 있다"; ok "(1) app 서버에는 프로비저너 비밀·CA 키가 없다"
grep -q 'step-ca:' "$T/r/app/compose.placement.yaml" && ok "(2) app 서버 override 에 extra_hosts step-ca:<호스트>" || bad "extra_hosts step-ca 없음"
[ "$(docker inspect -f '{{.State.Health.Status}}' $A-release-gate-cert-1)" = healthy ] || bad "release-gate-cert 가 healthy 가 아니다"
S=$(docker run --rm --network none -v ${A}_certs-release-gate:/c:ro "$UTIL" cat /c/tls.crt | openssl x509 -noout -subject -issuer 2>/dev/null)
case "$S" in *"CN = release-gate"*|*"CN=release-gate"*) ok "(2) app 서버 -cert 가 다른 망의 step-ca 에서 서비스 이름(release-gate) 인증서를 받았다";; *) bad "인증서 주체: $S";; esac
[ "$(docker inspect -f '{{.State.Health.Status}}' $A-release-gate-gw-1)" = healthy ] && ok "(2) 영역 게이트웨이가 그 인증서로 443 을 연다(healthy)" || bad "사이드카가 healthy 가 아니다"
# --- R3.2·R3.4·R4.1·DC-NET.1·R6.2: 실제 사이드카·<서비스>-net 구조에서, 다른 서버의 호출자가 보는 것 ---
CALL() { docker exec $D-survey-service-1 python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/',timeout=15).read().decode())"; }
R=$(CALL); case "$R" in "200 https://release-gate:"*" ok") ok "(R1.4) 다른 서버의 호출자가 https://<서비스 이름>:<게시 포트> 로 사이드카를 거쳐 앱 응답을 받는다 ($R)";; *) bad "기준 호출: $R";; esac
A_APP=$A-release-gate-1; A_TLS=$A-release-gate-gw-1; A_NET=$A-release-gate-net-1
waith() { local i; for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$1")" = healthy ] && return 0; sleep 1; done; return 1; }   # 복구는 준비 확인(healthcheck)으로 판단한다(R4.3)
notok() { case "$1" in 200\ *) return 1;; *) return 0;; esac; }
S0=$(docker inspect -f '{{.State.StartedAt}}' $A_TLS)
docker stop -t 2 $A_APP >/dev/null; R=$(CALL)
notok "$R" && case "$R" in "502 "*|"503 "*|"504 "*|"ERR "*) ok "(R3.2) 앱 컨테이너가 멈추면 다른 서버의 호출자는 실패를 본다, 앱 응답을 위조하지 않는다 ($R)";; *) bad "R3.2 응답: $R";; esac || bad "R3.2: 앱이 멈췄는데 200: $R"
docker start $A_APP >/dev/null; waith $A_APP || bad "앱이 healthy 로 돌아오지 않는다"; R=$(CALL); case "$R" in "200 "*" ok") ok "(R4.1) 앱 재시작 뒤 같은 이름·주소로 200 (다른 구성요소를 손대지 않음) ($R)";; *) bad "R4.1 복구: $R";; esac
[ "$(docker inspect -f '{{.State.StartedAt}}' $A_TLS)" = "$S0" ] || bad "앱 재시작에 사이드카가 같이 재시작됐다(네트워크 공간이 앱 수명과 묶였다)"; ok "(R3.2) 앱 stop/start 에 사이드카와 망 공간(-net)은 그대로"
SA=$(docker inspect -f '{{.State.StartedAt}}' $A_APP)
docker stop -t 2 $A_TLS >/dev/null; R=$(CALL)
notok "$R" && case "$R" in "ERR "*|"502 "*|"503 "*) ok "(R3.4) 사이드카가 멈추면 다른 서버의 호출자는 연결 실패를 본다 ($R)";; *) bad "R3.4 응답: $R";; esac || bad "R3.4: 사이드카가 멈췄는데 200: $R"
docker start $A_TLS >/dev/null; waith $A_TLS || bad "사이드카가 healthy 로 돌아오지 않는다"; R=$(CALL); case "$R" in "200 "*" ok") ok "(DC-NET.1) 사이드카 재시작 뒤 앱을 건드리지 않고 같은 주소로 200 ($R)";; *) bad "DC-NET.1 복구: $R";; esac
[ "$(docker inspect -f '{{.State.StartedAt}}' $A_APP)" = "$SA" ] || bad "사이드카 재시작에 앱이 같이 재시작됐다"; ok "(DC-NET.1) 사이드카 stop/start 에 앱은 재시작되지 않았다"
# R6.2: 인증서 발급용 망(pki)과 DB 망은 서로의 서비스에 닿지 않는다(계약 호출 관계 밖의 쌍)
PROBE() { docker run --rm --network "$1" "$UTIL" python -c "import socket,sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3); print('reachable')
except Exception: print('blocked')" "$2" "$3"; }
[ "$(PROBE ${D}_pki release-gate-db 5432)" = blocked ] && ok "(R6.2) 인증서 발급 망(pki)에서 release-gate-db 에 닿지 않는다" || bad "R6.2: pki 망에서 release-gate-db 에 닿는다"
[ "$(PROBE ${D}_db-gate step-ca $SCP)" = blocked ] && ok "(R6.2) DB 망에서 step-ca 에 닿지 않는다" || bad "R6.2: DB 망에서 step-ca 에 닿는다"
# R1.5·R1.7: compose 밖 호출자는 내보낸 루트 + hosts 표 + 서비스 토큰만으로 부른다(배포 내부 구조를 모른다). 기본 브리지의 새 컨테이너로 시험한다
EXP="$T/export"; docker run --rm --network none -v ${D}_pki-root:/r:ro "$UTIL" cat /r/root_ca.crt > "$T/root.pem"
"$PY" scripts/placement.py export "$T/inv.yml" --compose "$T/compose.subset.yaml" --out "$EXP" --root-ca "$T/root.pem" >/dev/null || bad "내보내기 실패"
( cd "$EXP" && sha256sum -c SHA256SUMS >/dev/null ) || bad "내보낸 파일의 SHA-256 대조 실패"; ok "(R1.5) 내보낸 파일(루트·hosts·포트 표)의 SHA-256 목록이 맞는다"
XADDR=$(awk '$2=="release-gate"{print $1}' "$EXP/hosts"); XPORT=$(awk -F'\t' '$1=="release-gate"{print $2}' "$EXP/ports.tsv")
if [ "$XPORT" = 443 ]; then   # 추론 서버(다른 호스트) 경로: compose.inference.remote.yaml 이 주는 이름 해석(release-gate:<주소>)과 같은 줄로, https://release-gate (443) 가 실제로 닿는다
  RMT=$(INFERENCE_RELEASE_ADDR="$XADDR" INFERENCE_IMAGE=x INFERENCE_PAUSE_IMAGE=x INFERENCE_STEP_IMAGE=x INFERENCE_GATEWAY_IMAGE=x INFERENCE_EXPOSURE_FILE="$T/gw/exposure.json" INFERENCE_TOKENS_FILE="$T/gw/exposure.json" INFERENCE_RELEASE_TOKEN_FILE="$T/gw/exposure.json" INFERENCE_CA_FILE="$EXP/root_ca.crt" INFERENCE_PKI_ROOT_FILE="$EXP/root_ca.crt" INFERENCE_STEP_CA_URL=https://x INFERENCE_TLS_TOKEN_FILE="$T/gw/exposure.json" INFERENCE_TLS_NAME=x SECRETS_GID=0 docker compose -p infrmt-$$ -f compose.inference.yaml -f compose.inference.remote.yaml config --format json 2>/dev/null | python3 -c "import json,sys;print(' '.join(json.load(sys.stdin)['services']['model-serving-net']['extra_hosts']))")
  case "$RMT" in *"release-gate=$XADDR"*|*"release-gate:$XADDR"*) ok "(R1.5) compose.inference.remote.yaml 의 extra_hosts 가 hosts 표의 release-gate 줄과 같다";; *) bad "remote overlay 해석: $RMT";; esac
  [ "$(docker run --rm --add-host "release-gate:$XADDR" -e SSL_CERT_FILE=/x/root_ca.crt -v "$EXP:/x:ro" "$UTIL" python -c "import urllib.request;print(urllib.request.urlopen('https://release-gate/',timeout=8).read().decode())" 2>&1)" = ok ] && ok "(R1.5) 추론 서버 경로: https://release-gate (포트 443 게시)가 OUT-FILE 루트 + hosts 표로 닿는다" || bad "https://release-gate:443 이 닿지 않는다"
else echo "SKIP: 호스트의 443 이 사용 중이라 게시 포트 443 단언을 건너뛴다(통과로 세지 않는다)"; fi
XC="import urllib.request;print(urllib.request.urlopen('https://release-gate:$XPORT/',timeout=8).read().decode())"
[ "$(docker run --rm --add-host release-gate:$XADDR -e SSL_CERT_FILE=/x/root_ca.crt -v "$EXP:/x:ro" "$UTIL" python -c "$XC" 2>&1)" = ok ] && ok "(R1.5) compose 밖 호출자가 내보낸 루트 + hosts 표만으로 https 검증을 통과해 앱 응답을 받는다" || bad "R1.5: 내보낸 파일만으로 호출 실패"
docker run --rm --add-host release-gate:$XADDR "$UTIL" python -c "$XC" >/dev/null 2>&1 && bad "R1.5: 루트 없이 호출이 통과했다" || ok "(R1.5) 루트 없이는 검증 실패(변이 확인)"
O=$(docker run --rm --network none -v ${D}_release-gate-db-pgtls:/p:ro "$UTIL" stat -c %u /p/tls.key); [ "$O" = 999 ] || bad "release-gate-db-pgtls 의 tls.key 소유자 $O"; ok "(3) release-gate-db-cert 의 pg-tls 소유자 999"
DSN="$T/r/app/secrets/tokens/db-gate-dsn"; grep -q "@release-gate-db:$PGP/" "$DSN" && grep -q 'sslmode=verify-full' "$DSN" || bad "app 서버 DSN 의 호스트·sslmode"
ok "(3) app 서버 DSN = release-gate-db:$PGP, sslmode=verify-full"
R=$(docker run --rm --network ${A}_serving --add-host release-gate-db:$HOSTADDR -v ${A}_pki-root:/etc/openit/pki:ro -v "$DSN:/dsn:ro" "$PGIMG" sh -c 'psql "$(cat /dsn)" -qAt -c "select 1"' 2>&1) || { echo "$R" | tail -3 | cut -c1-200 >&2; bad "app 서버 DSN 으로 다른 망의 release-gate-db 에 verify-full 접속 실패"; }
[ "$R" = 1 ] && ok "(3) 다른 망의 release-gate-db 에 sslmode=verify-full 로 접속했다(서버 인증서 이름 release-gate-db, step-ca 루트 검증)"
R=$(docker run --rm --network ${A}_serving --add-host release-gate-db:$HOSTADDR -v ${A}_pki-root:/etc/openit/pki:ro -v "$DSN:/dsn:ro" "$PGIMG" sh -c 'psql "$(sed "s/verify-full/disable/" /dsn)" -qAt -c "select 1"' 2>&1) && bad "TLS 없는 접속이 통과했다" || ok "(3) TLS 없는 접속은 거부된다(hostssl 만)"
timeout 600 "$AP" -i "$T/inv.yml" ansible/site.yml --connection=local >"$T/run2.log" 2>&1 || { tail -25 "$T/run2.log" >&2; bad "플레이북 2회차 실패"; }
if grep -aE '^[a-z0-9-]+ +: ok=' "$T/run2.log" | grep -v 'changed=0 '; then bad "2회차에 바뀐 것이 있다(멱등 아님)"; fi
ok "(4) 플레이북 2회차 changed=0"
echo "PASS: 분리 배치 인증서·DB 경로 시험"
