#!/usr/bin/env bash
# 추론 서버 -> 주 서버 release-gate 길 단독 시험, 같은 호스트 경로(RUNTIME R1.5·R1.8, Docker 필요).
# compose 표준: 추론 서버의 pod 가 주 서버 프로젝트의 inference-in 망에 `networks: external: true` 로 붙고, release-gate 영역 게이트웨이가 그 망에서 별칭 release-gate 를 가진다 -> Docker DNS 로 https://release-gate 가 풀린다(IP·extra_hosts 없음).
# 이 시험이 보는 것: (1) release-gate 영역 게이트웨이(platform area-gateway 이미지, 대역 상류)만 띄운 망 하나(주 서버 inference-in 의 대역).
# (2) compose.inference.yaml + compose.inference.samehost.yaml 의 `docker compose config` 가 model-serving-net 을 그 외부 망에만 붙인다.
# (3) 추론 쪽 컨테이너를 config 가 정한 망에 붙여 OUT-FILE 루트만 믿고 https://release-gate/healthz 가 200.
# (4) 변이: 외부 망을 빼면(기본 브리지) 이름이 풀리지 않아 실패 / 틀린 루트는 TLS 검증이 실패. 다른 서버 경로(OUT-FILE hosts 표 + 443 게시)는 분리 배치 시험이 실제 기동으로 본다. 고정 포트 없음.
set -uo pipefail
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"
DEPLOY_NO_DOCKER=1; source scripts/lib.sh; detect_docker
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
ID=$$; T=$(mktemp -d); NET=inf-reach-$ID; : > "$T/names"
cleanup() { for n in $(cat "$T/names" 2>/dev/null); do "$DOCKER" rm -f "$n" >/dev/null 2>&1; done; "$DOCKER" network rm "$NET" >/dev/null 2>&1; rm -rf "$T"; }; trap cleanup EXIT
GW_IMG=$(awk '$1=="area-gateway"{print $2}' build/images.env 2>/dev/null)
[ -n "$GW_IMG" ] && "$DOCKER" image inspect "$GW_IMG" >/dev/null 2>&1 || { echo "SKIP: area-gateway 이미지가 없다(scripts/build-images.sh area-gateway)"; exit 77; }
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' locks/images.lock); PAUSE=$(sed -n 's/^PAUSE_IMAGE=//p' locks/images.lock)
# OUT-FILE: 루트 + hosts 표 + SHA256SUMS (주 서버가 내보내는 것과 같은 도구). hosts 표는 다른 서버 경로의 입력이고 같은 호스트에서는 쓰지 않는다
mkdir -p "$T/pki" "$T/out" "$T/certs"; gateway_test_pki "$T/pki" release-gate || bad "시험 PKI 실패"
bash scripts/export-out-files.sh --out "$T/out" --root "$T/pki/root_ca.crt" --host "10.0.0.1 release-gate" >/dev/null || bad "OUT-FILE 내보내기 실패"
( cd "$T/out" && sha256sum -c SHA256SUMS >/dev/null ) || bad "OUT-FILE 대조 실패"; ok "OUT-FILE(루트 + SHA256SUMS) 대조 통과"
cp "$T/pki/leaf.crt" "$T/certs/tls.crt"; cp "$T/pki/leaf.key" "$T/certs/tls.key"; chmod 644 "$T/certs/"*
echo '{"service":"release-gate","routes":[{"paths":["/healthz"],"methods":["GET"],"auth":{"kind":"none"},"user_header":"strip"}],"egress":[]}' > "$T/exposure.json"; chmod 644 "$T/exposure.json"
mkdir "$T/app"; cat > "$T/app/app.py" <<'PY'
import http.server as h
class H(h.BaseHTTPRequestHandler):
    def do_GET(s):
        s.send_response(200); s.send_header("Content-Type", "application/json"); s.end_headers(); s.wfile.write(b'{"status":"ok"}')
    def log_message(s, *a): pass
h.ThreadingHTTPServer(("127.0.0.1", 8080), H).serve_forever()
PY
"$DOCKER" network create --internal "$NET" >/dev/null || bad "시험 망 만들기 실패"
P=rg-pod-$ID   # release-gate 영역 pod(pause) + 대역 상류 + 영역 게이트웨이. pod 는 망 $NET 에서 별칭 release-gate 를 가진다(주 서버 compose.yaml 의 release-gate-net 의 inference-in 별칭과 같다)
"$DOCKER" run -d --name "$P" --network "$NET" --network-alias release-gate --sysctl net.ipv4.ip_unprivileged_port_start=0 --read-only --cap-drop ALL "$PAUSE" >/dev/null || bad "pause 실패"; echo "$P" >> "$T/names"
"$DOCKER" run -d --name "$P-app" --network "container:$P" -v "$T/app:/app:ro" "$UTIL" python /app/app.py >/dev/null || bad "대역 상류 실패"; echo "$P-app" >> "$T/names"
"$DOCKER" run -d --name "$P-gw" --network "container:$P" --read-only --tmpfs /tmp --cap-drop ALL -v "$T/certs:/certs:ro" -v "$T/exposure.json:/etc/openit/exposure.json:ro" \
  -e AREA_GATEWAY_UPSTREAM=127.0.0.1:8080 "$GW_IMG" >/dev/null || bad "영역 게이트웨이 실패"; echo "$P-gw" >> "$T/names"
up=0; for i in $(seq 1 60); do "$DOCKER" exec "$P-app" python -c "import socket;socket.create_connection(('127.0.0.1',443),timeout=1)" >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
[ $up = 1 ] || { "$DOCKER" logs "$P-gw" 2>&1 | tail -5 >&2; bad "영역 게이트웨이가 443 을 열지 않았다"; }
# 추론 쪽: 같은 호스트 overlay 를 합친 compose 해석에서 model-serving-net 이 붙는 외부 망과 이름을 꺼낸다(더미 변수, 파일은 빈 파일)
for f in tok rtok ca tlstok; do : > "$T/$f"; done; : > "$T/exposure.dummy"
CFG=$(INFERENCE_IMAGE=x INFERENCE_PAUSE_IMAGE=x INFERENCE_STEP_IMAGE=x INFERENCE_GATEWAY_IMAGE=x INFERENCE_EXPOSURE_FILE="$T/exposure.dummy" INFERENCE_TOKENS_FILE="$T/tok" INFERENCE_RELEASE_TOKEN_FILE="$T/rtok" INFERENCE_CA_FILE="$T/ca" INFERENCE_PKI_ROOT_FILE="$T/pki/root_ca.crt" \
  INFERENCE_STEP_CA_URL=https://x INFERENCE_TLS_TOKEN_FILE="$T/tlstok" INFERENCE_TLS_NAME=x INFERENCE_RELEASE_NETWORK="$NET" SECRETS_GID=0 \
  "$DOCKER" compose -p infreach-$ID -f compose.inference.yaml -f compose.inference.samehost.yaml config --format json 2>"$T/cfg.err") || { cat "$T/cfg.err" >&2; bad "compose.inference.yaml + samehost overlay 를 해석하지 못했다"; }
JOINED=$(printf '%s' "$CFG" | python3 -c "import json,sys;d=json.load(sys.stdin);n=d['services']['model-serving-net'];nets=list((n.get('networks') or {}).keys());print('|'.join(d['networks'][k]['name'] for k in nets if d['networks'][k].get('external')), n.get('network_mode',''), len(nets))")
[ "$JOINED" = "$NET  2" ] && ok "samehost overlay: model-serving-net 이 외부 망($NET)과 기본 망(게시 포트용)에 붙는다(network_mode 없음)" || bad "samehost overlay 해석: '$JOINED'"
fetch() { # fetch <루트 파일> <망>: 추론 쪽 컨테이너를 그 망에 붙여 release-gate 의 /healthz 를 https 로 -> 본문 status 까지 보고 상태 코드, 실패면 ERR
  "$DOCKER" run --rm --network "$2" -v "$1:/root_ca.crt:ro" -e SSL_CERT_FILE=/root_ca.crt "$UTIL" python -c "import urllib.request,sys
import json
try:
    r = urllib.request.urlopen('https://release-gate/healthz', timeout=8); b = json.loads(r.read()); print(r.status if b.get('status') == 'ok' else 'BODY')   # 본문의 status 까지 판정한다(R5.1)
except Exception as e: print('ERR', type(e).__name__)" 2>/dev/null | tail -1
}
[ "$(fetch "$T/out/root_ca.crt" "$NET")" = 200 ] && ok "외부 망의 별칭으로 https://release-gate/healthz 가 OUT-FILE 루트로 200 (Docker DNS)" || bad "추론 쪽에서 https://release-gate/healthz 가 200 이 아니다"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/other.key" -out "$T/other.crt" -subj /CN=other -days 2 >/dev/null 2>&1
case "$(fetch "$T/other.crt" "$NET")" in ERR*) ok "변이: 다른 루트로는 TLS 검증이 실패한다(OUT-FILE 루트만 믿는다)";; *) bad "변이: 틀린 루트로도 통과했다";; esac
case "$(fetch "$T/out/root_ca.crt" bridge)" in ERR*) ok "변이: 외부 망을 빼면(기본 브리지) release-gate 이름이 풀리지 않아 닿지 못한다";; *) bad "변이: 외부 망 없이 닿았다";; esac
echo "PASS: 추론 서버 -> release-gate 영역 게이트웨이 단독 시험(같은 호스트, 외부 망 별칭)"
