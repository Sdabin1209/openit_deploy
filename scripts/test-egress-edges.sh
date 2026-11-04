#!/usr/bin/env bash
# 영역 사이 호출 단독 기동 시험(INTERFACES I1~I7·I9·I10, RUNTIME R1.8, 계약 Exposure.egress): 연결 목록을 손으로 쓰지 않는다. 영역 이미지의 라벨 io.openit.exposure 의 egress 에서 (부르는 쪽 -> 받는 쪽)을 기계로 뽑는다.
# 연결마다 부르는 쪽 영역 게이트웨이와 받는 쪽 영역 게이트웨이(뒤에 대역 상류 하나)만 띄우고, 부르는 쪽 pod 안에서 OPENIT_EGRESS_PROXY(127.0.0.1:3128)로 CONNECT(RFC 9110 9.3.6)를 열어 https://<받는 쪽>/healthz 가 루트 인증서 검증으로 200 인지 본다.
# egress 에 없는 상대(목록 밖의 아무 영역)는 403 + EGRESS_DENIED 인지도 본다. external:* 는 영역 서비스가 아니라 이 시험에서 뺀다(개수를 알린다). 이미지는 build/images.env 의 로컬 이미지(scripts/build-images.sh)다.
# 변이: EGRESS_MUTATE=1 이면 첫 연결의 받는 쪽 이름을 부르는 쪽 egress 에서 빼고 돈다 -> 그 연결의 200 단언이 깨져 이 시험이 rc=1 로 실패해야 한다(scripts/test-egress-edges-mutation.sh 가 그것을 확인한다).
# 종료 코드: 0 모든 연결 통과(연결 수 == PASS 수), 1 실패, 77 이미지 없음(건너뜀: 통과로 세지 않는다). 고정 포트 없음(내부 망, 게시 포트 없음).
set -uo pipefail
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"
DEPLOY_NO_DOCKER=1; source scripts/lib.sh; detect_docker
ID=$$; T=$(mktemp -d); NET=""; : > "$T/names"; : > "$T/nets"
cleanup() { for n in $(cat "$T/names"); do "$DOCKER" rm -f "$n" >/dev/null 2>&1; done; for n in $(cat "$T/nets"); do "$DOCKER" network rm "$n" >/dev/null 2>&1; done; rm -rf "$T"; }; trap cleanup EXIT
GW_IMG=$(awk '$1=="area-gateway"{print $2}' build/images.env 2>/dev/null)
[ -n "$GW_IMG" ] && "$DOCKER" image inspect "$GW_IMG" >/dev/null 2>&1 || { echo "SKIP: area-gateway 이미지가 없다(scripts/build-images.sh area-gateway)"; exit 77; }
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' locks/images.lock); PAUSE=$(sed -n 's/^PAUSE_IMAGE=//p' locks/images.lock)
# 1) 라벨에서 선언을 꺼낸다: build/images.env 의 모든 이미지 중 io.openit.exposure 가 있는 것 -> $T/exp/<service>.json
mkdir -p "$T/exp"
while read -r name tag _; do
  [ -n "$name" ] || continue
  lab=$("$DOCKER" image inspect "$tag" --format '{{index .Config.Labels "io.openit.exposure"}}' 2>/dev/null) || continue
  case "$lab" in ""|"<no value>") continue;; esac
  printf '%s' "$lab" | python3 -c "import json,sys;d=json.load(sys.stdin);open(sys.argv[1]+'/'+d['service']+'.json','w').write(json.dumps(d))" "$T/exp" || { echo "FAIL: $name 의 라벨 io.openit.exposure 가 JSON 이 아니다" >&2; exit 1; }
done < build/images.env
# 2) 연결 = (부르는 쪽, 받는 쪽): egress 의 영역 서비스 이름 전부. 받는 쪽 선언이 없는 연결도 목록에 넣는다(아래에서 실패로 센다: 호출 관계가 가리키는 상대가 없으면 런타임에 이름이 풀리지 않는다)
python3 - "$T/exp" > "$T/edges" <<'PY'
import json, pathlib, sys
exp = {p.stem: json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob("*.json")}
for a, d in sorted(exp.items()):
    for b in d.get("egress", []):
        if not b.startswith("external:"): print(a, b)
PY
[ -z "${EGRESS_LIMIT:-}" ] || { head -n "$EGRESS_LIMIT" "$T/edges" > "$T/edges.l"; mv "$T/edges.l" "$T/edges"; }   # 변이 시험이 첫 연결만 돌리는 데 쓴다
N=$(wc -l < "$T/edges"); EXT=$(python3 -c "import json,pathlib,sys;print(sum(1 for p in pathlib.Path(sys.argv[1]).glob('*.json') for e in json.loads(p.read_text()).get('egress',[]) if e.startswith('external:')))" "$T/exp")
[ "$N" -gt 0 ] || { echo "FAIL: 연결이 하나도 없다(라벨을 읽지 못했다?)" >&2; exit 1; }
echo "연결 $N 개(영역 서비스 사이), external:* $EXT 개는 이 시험 밖"
ALL=$(ls "$T/exp" | sed 's/\.json$//' | tr '\n' ' ')
# 시험 PKI: 모든 서비스 이름을 SAN 으로 갖는 잎 인증서 하나(제품 PKI 는 step-ca 이고 이것은 시험 폴더 안에만 있다)
mkdir -p "$T/pki" "$T/certs"; gateway_test_pki "$T/pki" $ALL || { echo "FAIL: 시험 PKI 실패" >&2; exit 1; }
cp "$T/pki/leaf.crt" "$T/certs/tls.crt"; cp "$T/pki/leaf.key" "$T/certs/tls.key"; chmod 644 "$T/certs/"*
mkdir "$T/app"; cat > "$T/app/app.py" <<'PY'
import http.server as h
class H(h.BaseHTTPRequestHandler):
    def do_GET(s):
        s.send_response(200); s.send_header("Content-Type", "application/json"); s.end_headers(); s.wfile.write(b'{"status":"ok"}')
    def log_message(s, *a): pass
h.ThreadingHTTPServer(("127.0.0.1", 8080), H).serve_forever()
PY
# 부르는 쪽 pod 안에서 도는 클라이언트: 인자 <받는 쪽> -> CONNECT 응답 상태와 (200 이면) TLS 검증 뒤 GET /healthz 결과를 한 줄로 낸다
cat > "$T/client.py" <<'PY'
import json, os, socket, ssl, sys
proxy = os.environ["OPENIT_EGRESS_PROXY"].split("//", 1)[1].rstrip("/"); host, port = proxy.rsplit(":", 1)
target = sys.argv[1]
s = socket.create_connection((host, int(port)), timeout=8)
s.sendall(f"CONNECT {target}:443 HTTP/1.1\r\nHost: {target}:443\r\n\r\n".encode())
buf = b""
while b"\r\n\r\n" not in buf:
    c = s.recv(4096)
    if not c: break
    buf += c
head, _, rest = buf.partition(b"\r\n\r\n"); status = int(head.split(b" ")[1])
if status != 200:
    body = rest
    try:
        s.settimeout(2)
        while True:
            c = s.recv(4096)
            if not c: break
            body += c
    except Exception: pass
    print("CONNECT", status, "EGRESS_DENIED" if b"EGRESS_DENIED" in head + body else "OTHER"); sys.exit(0)
ctx = ssl.create_default_context(cafile="/root_ca.crt")   # 루트 인증서 검증을 끄지 않는다
t = ctx.wrap_socket(s, server_hostname=target)
t.sendall(f"GET /healthz HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\n\r\n".encode())
r = b""
while True:
    c = t.recv(4096)
    if not c: break
    r += c
line = r.split(b"\r\n", 1)[0].decode()
print("GET", line.split(" ")[1] if " " in line else line, "ok" if b'"status":"ok"' in r else "BODY")
PY
chmod 644 "$T/client.py"
pod() { # pod <이름> <별칭> <exposure 파일> <상류 대역 0|1>: pause + (대역 상류) + 영역 게이트웨이. 이름은 정리 목록에 넣는다
  local p=$1
  "$DOCKER" run -d --name "$p" --network "$NET" --network-alias "$2" --sysctl net.ipv4.ip_unprivileged_port_start=0 --read-only --cap-drop ALL "$PAUSE" >/dev/null || return 1; echo "$p" >> "$T/names"
  if [ "$4" = 1 ]; then "$DOCKER" run -d --name "$p-app" --network "container:$p" -v "$T/app:/app:ro" "$UTIL" python /app/app.py >/dev/null || return 1; echo "$p-app" >> "$T/names"; fi
  "$DOCKER" run -d --name "$p-gw" --network "container:$p" --read-only --tmpfs /tmp --cap-drop ALL -v "$T/certs:/certs:ro" -v "$3:/etc/openit/exposure.json:ro" \
    -e AREA_GATEWAY_UPSTREAM=127.0.0.1:8080 -e AREA_GATEWAY_INGRESS_PORT=443 -e AREA_GATEWAY_EGRESS_PORT=3128 "$GW_IMG" >/dev/null || return 1; echo "$p-gw" >> "$T/names"
}
ready() { local p=$1 i; for i in $(seq 1 60); do "$DOCKER" exec "$p" true >/dev/null 2>&1 || true; "$DOCKER" run --rm --network "container:$p" "$UTIL" python -c "import socket;socket.create_connection(('127.0.0.1',443),timeout=1)" >/dev/null 2>&1 && return 0; sleep 0.5; done; return 1; }
PASS=0; FAILS=0; I=0; MUT_DONE=0
while read -r A B; do
  I=$((I+1))
  if [ ! -f "$T/exp/$B.json" ]; then FAILS=$((FAILS+1)); echo "  FAIL 연결 $A -> $B: 받는 쪽 '$B' 의 선언(라벨 io.openit.exposure)이 이미지에 없다(egress 의 이름이 받는 서비스의 이름과 다르다: 서비스 이름은 $(ls "$T/exp" | sed 's/\.json$//' | tr '\n' ' '))" >&2; continue; fi
  NET=egress-$ID-$I; "$DOCKER" network create --internal "$NET" >/dev/null || { echo "FAIL: 망 만들기 실패" >&2; exit 1; }; echo "$NET" >> "$T/nets"
  cp "$T/exp/$A.json" "$T/caller.json"
  if [ "${EGRESS_MUTATE:-0}" = 1 ] && [ $MUT_DONE = 0 ]; then   # 변이: 받는 쪽 이름을 부르는 쪽 egress 에서 뺀다
    python3 - "$T/caller.json" "$B" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["egress"] = [e for e in d["egress"] if e != sys.argv[2]]; json.dump(d, open(sys.argv[1], "w"))
PY
    MUT_DONE=1
  fi
  cp "$T/exp/$B.json" "$T/callee.json"; chmod 644 "$T/caller.json" "$T/callee.json"
  if ! pod "eg$ID-$I-b" "$B" "$T/callee.json" 1 || ! pod "eg$ID-$I-a" "$A" "$T/caller.json" 0; then echo "FAIL: 연결 $A -> $B: pod 를 띄우지 못했다" >&2; FAILS=$((FAILS+1)); continue; fi
  ready "eg$ID-$I-b" && ready "eg$ID-$I-a" || { echo "FAIL: 연결 $A -> $B: 영역 게이트웨이가 443 을 열지 않았다" >&2; "$DOCKER" logs "eg$ID-$I-a-gw" 2>&1 | tail -3 >&2; FAILS=$((FAILS+1)); continue; }
  run() { "$DOCKER" run --rm --network "container:eg$ID-$I-a" -e OPENIT_EGRESS_PROXY=http://127.0.0.1:3128 -v "$T/pki/root_ca.crt:/root_ca.crt:ro" -v "$T/client.py:/client.py:ro" "$UTIL" python /client.py "$1" 2>&1 | tail -1; }
  POS=$(run "$B")
  # 음성: 부르는 쪽 egress 에도 자기 자신에도 없는 상대(받는 쪽 선언이 있는 다른 서비스) -> 403 EGRESS_DENIED. 상대 서비스는 이 pod 망에 없어도 허용 판정이 먼저다
  OTHER=$(python3 - "$T/exp" "$A" "$B" <<'PY'
import json, pathlib, sys
exp = {p.stem: json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob("*.json")}
a = sys.argv[2]; allowed = set(exp[a].get("egress", [])) | {a, sys.argv[3]}
print(next((n for n in sorted(exp) if n not in allowed), ""))
PY
)
  NEG=$(run "${OTHER:-nonexistent-service}")
  if [ "$POS" = "GET 200 ok" ] && [ "$NEG" = "CONNECT 403 EGRESS_DENIED" ]; then PASS=$((PASS+1)); echo "  PASS $A -> $B (CONNECT 200 + 루트 검증 + /healthz 200; 목록 밖 ${OTHER:-nonexistent-service}: 403 EGRESS_DENIED)"
  else FAILS=$((FAILS+1)); echo "  FAIL 연결 $A -> $B: 허용 호출 결과 '$POS' (기대 'GET 200 ok'), 목록 밖($OTHER) 결과 '$NEG' (기대 'CONNECT 403 EGRESS_DENIED')" >&2; fi
  for n in $(grep -- "eg$ID-$I-" "$T/names"); do "$DOCKER" rm -f "$n" >/dev/null 2>&1; done; "$DOCKER" network rm "$NET" >/dev/null 2>&1
done < "$T/edges"
echo "연결 $N, PASS $PASS, FAIL $FAILS"
[ "$PASS" = "$N" ] && [ "$FAILS" = 0 ] && exit 0 || exit 1
