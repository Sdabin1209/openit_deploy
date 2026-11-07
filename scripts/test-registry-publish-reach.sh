#!/usr/bin/env bash
# 학습 서버(compose 밖 호출자) -> 주 서버 model-registry 게시 길 단독 시험(RUNTIME R1.5·R1.8·R3.23, HTTP.md I3 publish, Docker 필요). 설계는 ADR 0071.
# "다른 서버"는 같은 Docker 호스트의 별도 망 하나로 흉내 낸다: 호출자 pod 는 OUT-FILE hosts 표의 `<주소> model-registry` 줄을 --add-host 로 받아 받는 pod 의 주소로 간다(호스트 포트 게시 없음, 고정 포트 없음).
# 보는 것:
#  (1) OUT-FILE(export-out-files.sh: 루트·hosts 표·SHA256SUMS)을 내보내고 sha256sum -c 로 대조한다.
#  (2) 받는 쪽 = 실제 model-registry 이미지 + platform area-gateway(받는 영역 게이트웨이, 서비스 이름 인증서). OUT-FILE 루트·hosts 표로 https://model-registry 에 닿고,
#      토큰 대조는 받는 서비스가 한다(R3.23, 3.4.4: 게이트웨이는 대조하지 않는다): 토큰 없음 401·틀린 토큰 401(BoundaryError 본문), 읽기 토큰(release-gate)의 게시 403, 쓰기 토큰(model-lab)의 게시는 401·403 이 아니다(서버가 역할을 받아들여 본문 검증으로 간다).
#  (3) 호출자 쪽 = 같은 서버에 둔 자기 영역 게이트웨이(platform area-gateway)의 출구(R1.8). 출구의 허용 목록은 model-lab 영역이 낸 Exposure 선언(model-registry 이미지 라벨 io.openit.exposure,
#      state/gateways/model-registry/exposure.json)이다. 출구 판정이 선언과 같다(선언한 상대만 터널, 아닌 상대는 403). 선언에 model-registry 가 있으면 출구를 거쳐 (2)와 같은 쓰기 단언을 한다.
#      선언에 없으면 그 길은 계약상 열리지 않으므로 검증하지 못한 것이다: 사유를 내고 종료 77(SKIP, 통과 아님). docs/change-requests/CR-450-model-lab-egress-model-registry.md
#  공개 입구에 게시 경로가 없다는 것(401/404)은 실제 공개 입구가 필요해 scripts/test-inference-location.sh 가 본다.
# 자원 이름은 deploy-regpub-<PID> 접두사, 작업 폴더는 git 제외 state/ 아래(재부팅에 지워지는 /tmp 를 쓰지 않는다). 끝나면 이 시험이 만든 것만 지운다.
set -uo pipefail
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"
DEPLOY_NO_DOCKER=1; source scripts/lib.sh; detect_docker
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
ID=$$; T="$D/state/regpub-reach-$ID"; NET=deploy-regpub-$ID; P=deploy-regpub-$ID
mkdir -p "$T"; : > "$T/names"
cleanup() { for n in $(cat "$T/names" 2>/dev/null); do "$DOCKER" rm -f "$n" >/dev/null 2>&1; done; "$DOCKER" volume rm "$P-data" >/dev/null 2>&1; "$DOCKER" network rm "$NET" >/dev/null 2>&1; rm -rf "$T"; }; trap cleanup EXIT
img() { awk -v n="$1" '$1==n{print $2}' build/images.env 2>/dev/null; }
GW_IMG=$(img area-gateway); MR_IMG=$(img model-registry)
for x in "$GW_IMG" "$MR_IMG"; do [ -n "$x" ] && "$DOCKER" image inspect "$x" >/dev/null 2>&1 || { echo "SKIP: area-gateway·model-registry 이미지가 없다(scripts/build-images.sh area-gateway model-registry)"; exit 77; }; done
EXP="${GATEWAYS_DIR:-$D/state/gateways}/model-registry/exposure.json"   # model-lab 영역의 Exposure 선언(이미지 라벨에서 gen-gateways.py 가 꺼낸 것). deploy 가 쓰지 않는다
[ -s "$EXP" ] || { echo "SKIP: $EXP 가 없다(scripts/gen-gateways.py)"; exit 77; }
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' locks/images.lock); PAUSE=$(sed -n 's/^PAUSE_IMAGE=//p' locks/images.lock)
GID=$(id -g)

# 시험 PKI(서비스 이름 model-registry 인증서)와 토큰 목록 파일. 값은 이 폴더 안에서만 쓰고 출력하지 않는다
mkdir -p "$T/pki" "$T/certs" "$T/out" "$T/sec"; chmod 750 "$T/sec"   # 750: 컨테이너(uid 10001)는 --group-add 의 그룹으로만 들어온다(누구나 읽기 아님, ADR 0054)
gateway_test_pki "$T/pki" model-registry || bad "시험 PKI 실패"
cp "$T/pki/leaf.crt" "$T/certs/tls.crt"; cp "$T/pki/leaf.key" "$T/certs/tls.key"; chmod 644 "$T/certs/"* "$T/pki/root_ca.crt"
cp "$EXP" "$T/exposure.json"; chmod 644 "$T/exposure.json"
RT=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'); WT=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf 'release-gate=%s\n' "$RT" > "$T/sec/read-tokens"; printf 'model-lab=%s\n' "$WT" > "$T/sec/write-tokens"
printf '%s' "$RT" > "$T/sec/read"; printf '%s' "$WT" > "$T/sec/write"; chmod 640 "$T/sec/"*   # 컨테이너는 --group-add 로 읽는다(ADR 0054)
unset RT WT

"$DOCKER" network create "$NET" >/dev/null || bad "시험 망 만들기 실패"
# 받는 쪽(주 서버 역할): model-registry pod = pause + 실제 model-registry + 받는 영역 게이트웨이(compose.yaml 의 model-registry-net/-gw 와 같은 모양)
"$DOCKER" run -d --name "$P-mr" --network "$NET" --sysctl net.ipv4.ip_unprivileged_port_start=0 --read-only --cap-drop ALL "$PAUSE" >/dev/null || bad "받는 pod 실패"; echo "$P-mr" >> "$T/names"
"$DOCKER" run -d --name "$P-mr-app" --network "container:$P-mr" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true --group-add "$GID" \
  -v "$P-data:/data" -v "$T/sec:/run/secrets:ro" -v "$T/pki/root_ca.crt:/etc/openit/pki/root_ca.crt:ro" \
  -e MODEL_REGISTRY_READ_TOKENS_FILE=/run/secrets/read-tokens -e MODEL_REGISTRY_WRITE_TOKENS_FILE=/run/secrets/write-tokens -e MODEL_REGISTRY_HOST=127.0.0.1 \
  -e SSL_CERT_FILE=/etc/openit/pki/root_ca.crt -e OPENIT_EGRESS_PROXY=http://127.0.0.1:3128 "$MR_IMG" >/dev/null || bad "model-registry 실패"; echo "$P-mr-app" >> "$T/names"
"$DOCKER" run -d --name "$P-mr-gw" --network "container:$P-mr" --read-only --tmpfs /tmp --cap-drop ALL -v "$T/certs:/certs:ro" -v "$T/exposure.json:/etc/openit/exposure.json:ro" \
  -e AREA_GATEWAY_UPSTREAM=127.0.0.1:8080 -e AREA_GATEWAY_INGRESS_PORT=443 -e AREA_GATEWAY_EGRESS_PORT=3128 "$GW_IMG" >/dev/null || bad "받는 영역 게이트웨이 실패"; echo "$P-mr-gw" >> "$T/names"
ADDR=$("$DOCKER" inspect "$P-mr" --format "{{with index .NetworkSettings.Networks \"$NET\"}}{{.IPAddress}}{{end}}")
[ -n "$ADDR" ] || bad "받는 pod 의 주소를 읽지 못했다"

# (1) OUT-FILE: 주 서버가 내보내는 것과 같은 도구. 호출자는 대조를 통과한 파일만 쓴다(R1.5)
bash scripts/export-out-files.sh --out "$T/out" --root "$T/pki/root_ca.crt" --host "$ADDR model-registry" >/dev/null || bad "OUT-FILE 내보내기 실패"
( cd "$T/out" && sha256sum -c --quiet SHA256SUMS ) || bad "OUT-FILE 대조 실패"
HADDR=$(awk '$2=="model-registry"{print $1}' "$T/out/hosts"); [ "$HADDR" = "$ADDR" ] || bad "OUT-FILE hosts 표에 model-registry 줄이 없다"
ok "OUT-FILE(루트·hosts 표 '<주소> model-registry'·SHA256SUMS) 대조 통과"

# 호출자 쪽(학습 서버 역할): pod 는 hosts 표로 이름을 풀고(--add-host), 같은 서버의 자기 영역 게이트웨이가 출구(3128)다
"$DOCKER" run -d --name "$P-lab" --network "$NET" --add-host "model-registry:$HADDR" --read-only --cap-drop ALL "$PAUSE" >/dev/null || bad "호출자 pod 실패"; echo "$P-lab" >> "$T/names"
"$DOCKER" run -d --name "$P-lab-gw" --network "container:$P-lab" --read-only --tmpfs /tmp --cap-drop ALL -v "$T/certs:/certs:ro" -v "$T/exposure.json:/etc/openit/exposure.json:ro" \
  -e AREA_GATEWAY_UPSTREAM=127.0.0.1:8080 -e AREA_GATEWAY_INGRESS_PORT=443 -e AREA_GATEWAY_EGRESS_PORT=3128 "$GW_IMG" >/dev/null || bad "호출자 영역 게이트웨이 실패"; echo "$P-lab-gw" >> "$T/names"

# 준비 확인: 받는 게이트웨이가 443 을, 호출자 게이트웨이가 3128 을 열고 model-registry 가 /healthz 를 낼 때까지(상한 60초: 측정하지 않았다. 컨테이너 기동은 수 초 규모라는 판단, D125)
wait_ready "받는 영역 게이트웨이 443 -> model-registry /healthz" 60 "$DOCKER" run --rm --network "container:$P-lab" -v "$T/out/root_ca.crt:/r.crt:ro" -e SSL_CERT_FILE=/r.crt "$UTIL" \
  python -c "import json,sys,urllib.request;d=json.loads(urllib.request.urlopen('https://model-registry/healthz',timeout=3).read());st=d.get('status');sys.exit(0 if ((st=='ok') if st is not None else d.get('ready') is True) else 1)" || { "$DOCKER" logs "$P-mr-app" 2>&1 | tail -5 >&2; "$DOCKER" logs "$P-mr-gw" 2>&1 | tail -3 >&2; bad "model-registry 가 준비되지 않았다"; }
wait_ready "호출자 영역 게이트웨이 3128" 30 "$DOCKER" run --rm --network "container:$P-lab" "$UTIL" python -c "import socket;socket.create_connection(('127.0.0.1',3128),timeout=1)" || bad "호출자 영역 게이트웨이가 3128 을 열지 않았다"

# 호출 도구: 호출자 pod 의 공간에서 OUT-FILE 루트만 믿고 https://model-registry 를 부른다. MODE=direct 는 출구 없이(받는 쪽 확인), egress 는 자기 영역 게이트웨이 출구로(R1.8)
probe() { # probe <direct|egress> -> 줄마다 "<이름> <코드> <BoundaryError code 또는 ->"
  "$DOCKER" run --rm --network "container:$P-lab" --read-only --cap-drop ALL --user 10001:10001 --group-add "$GID" -v "$T/out/root_ca.crt:/r.crt:ro" -v "$T/sec:/s:ro" -e MODE="$1" "$UTIL" python -c '
import io, json, os, ssl, tarfile, urllib.request, urllib.error
ctx = ssl.create_default_context(cafile="/r.crt")
hs = [urllib.request.HTTPSHandler(context=ctx)]
hs.append(urllib.request.ProxyHandler({"https": "http://127.0.0.1:3128"} if os.environ["MODE"] == "egress" else {}))
op = urllib.request.build_opener(*hs)
tok = {n: open("/s/" + n).read().strip() for n in ("read", "write")}
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as t: pass   # 빈 묶음: 서버가 역할을 받아들인 뒤 본문 검증에서 거절한다(게시 성공 자체는 E2E 단계 3 이 실제 패키지로 본다)
cases = [("list-read", "GET", "/v1/packages", "read", None), ("post-none", "POST", "/v1/packages", None, buf.getvalue()),
         ("post-wrong", "POST", "/v1/packages", "wrong", buf.getvalue()), ("post-read", "POST", "/v1/packages", "read", buf.getvalue()),
         ("post-write", "POST", "/v1/packages", "write", buf.getvalue())]
for name, m, path, who, body in cases:
    h = {"Content-Type": "application/x-tar"} if body is not None else {}
    if who: h["Authorization"] = "Bearer " + (tok.get(who) or "wrong-token")
    try:
        with op.open(urllib.request.Request("https://model-registry" + path, data=body, method=m, headers=h), timeout=20) as r: code, b = r.status, r.read()
    except urllib.error.HTTPError as e: code, b = e.code, e.read()
    except OSError as e: code, b = "ERR:" + type(e).__name__ + ":" + str(getattr(e, "reason", e))[:60].replace(" ", "_"), b""
    try: bc = json.loads(b).get("code") or "-"
    except Exception: bc = "-"
    print(name, code, bc)
' 2>"$T/probe.err"
}
expect_receiver() { # expect_receiver <출력> <길 이름>: (2) 의 단언
  local o=$1 w=$2 c
  c=$(awk '$1=="list-read"{print $2}' <<<"$o"); [ "$c" = 200 ] || bad "$w: 읽기 토큰 GET /v1/packages 가 $c"
  c=$(awk '$1=="post-none"{print $2" "$3}' <<<"$o"); [ "$c" = "401 PERMISSION_DENIED" ] || bad "$w: 토큰 없는 게시가 '$c'(받는 서비스의 401 BoundaryError 여야 한다, R3.23)"
  c=$(awk '$1=="post-wrong"{print $2" "$3}' <<<"$o"); [ "$c" = "401 PERMISSION_DENIED" ] || bad "$w: 틀린 토큰 게시가 '$c'"
  c=$(awk '$1=="post-read"{print $2" "$3}' <<<"$o"); [ "$c" = "403 PERMISSION_DENIED" ] || bad "$w: 읽기 토큰 게시가 '$c'(쓰기 역할이 아니면 403, R3.24)"
  c=$(awk '$1=="post-write"{print $2}' <<<"$o"); case "$c" in 4[0-9][0-9]|20[01]) [ "$c" != 401 ] && [ "$c" != 403 ] || bad "$w: 쓰기 토큰 게시가 $c(역할을 받아들이지 않았다)";; *) bad "$w: 쓰기 토큰 게시가 '$c'";; esac
  ok "$w: 받는 서비스가 토큰을 대조한다 — 읽기 GET 200, 무토큰·틀린 토큰 게시 401, 읽기 토큰 게시 403, 쓰기 토큰(model-lab) 게시는 역할 통과 후 본문 판정 $c"
}
# (2) 받는 쪽: hosts 표 + OUT-FILE 루트로 받는 영역 게이트웨이까지
OUT=$(probe direct) || { cat "$T/probe.err" >&2; bad "호출 도구 실패(direct)"; }
expect_receiver "$OUT" "hosts 표 -> model-registry 영역 게이트웨이"

# (3) 호출자 출구(R1.8): 판정이 model-lab 영역의 Exposure.egress 선언과 같은가
connect() { "$DOCKER" run --rm --network "container:$P-lab" "$UTIL" python -c '
import socket, sys
s = socket.create_connection(("127.0.0.1", 3128), timeout=5); s.sendall(("CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n\r\n" % (sys.argv[1], sys.argv[1])).encode())
print(s.recv(200).split(b"\r\n")[0].split()[1].decode())' "$1"; }
declared() { python3 -c 'import json,sys;sys.exit(0 if sys.argv[2] in (json.load(open(sys.argv[1])).get("egress") or []) else 1)' "$T/exposure.json" "$1"; }
UNDECL=survey-service; declared "$UNDECL" && bad "시험 전제: $UNDECL 이 model-lab 출구 선언에 있다(선언 밖 상대를 다른 이름으로 바꾼다)"
[ "$(connect "$UNDECL")" = 403 ] && ok "출구: 선언 밖 상대($UNDECL)는 403(EGRESS_DENIED, R1.8)" || bad "출구가 선언 밖 상대($UNDECL)에 터널을 열었다"
if declared model-registry; then
  [ "$(connect model-registry)" = 200 ] || bad "출구: 선언한 model-registry 에 터널이 열리지 않는다"
  OUT=$(probe egress) || { cat "$T/probe.err" >&2; bad "호출 도구 실패(egress)"; }
  expect_receiver "$OUT" "자기 영역 게이트웨이 출구(R1.8) -> model-registry 영역 게이트웨이"
  echo "PASS: 학습 서버 -> model-registry 게시 길(R1.5 OUT-FILE, 자기 출구 R1.8, 받는 서비스의 토큰 대조)"
  exit 0
fi
C=$(connect model-registry); [ "$C" = 403 ] || bad "출구: 선언에 없는 model-registry 에 터널이 열렸다($C)"
ok "출구: model-lab 영역의 Exposure.egress 에 model-registry 가 없어 출구가 403 으로 거절한다(선언대로)"
echo "SKIP: 학습 서버가 자기 영역 게이트웨이 출구(R1.8)로 model-registry 에 게시하는 길은 model-lab 의 Exposure 선언에 model-registry 가 생겨야 열린다. 검증하지 않았다(통과 아님) -- docs/change-requests/CR-450-model-lab-egress-model-registry.md"
exit 77
