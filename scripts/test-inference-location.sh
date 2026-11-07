#!/usr/bin/env bash
# 추론 서버 위치 독립 시험(D72, ADR 0070). 추론 서버를 "다른 호스트"처럼 별도 컴포즈 프로젝트로 띄워, 계약 R1.5 의 길(release-gate 영역 게이트웨이로 바로, OUT-FILE 루트, 서비스 토큰)로만 release-gate 를 읽는지 본다. 공개 입구에는 기계 경로가 없다(R3.23).
# 사용: scripts/test-inference-location.sh [--keep] [--rebuild]      (-h/--help)
#   --keep     끝나도 자원을 남긴다(디버깅). 정리: scripts/test-inference-location.sh --clean
#   --clean    이 시험이 만든 자원(deploy-e2e-loc* 프로젝트, state/loc-test)만 지운다
# 구성(샌드박스 방식: 운영 compose 에 시험용 문을 내지 않는다):
#   (가) 제품 = compose.yaml + compose.external-inference.yaml (운영 모드 그대로. compose.test.yaml 을 쓰지 않는다). 게이트웨이 TLS 포트만 호스트에 게시한다(Docker 배정).
#   (나) 다른 호스트 = compose.inference.yaml + compose.inference.samehost.yaml 을 별도 프로젝트로. 길은 R1.5: release-gate 영역 게이트웨이로 바로(외부 망 <P>_inference-in 의 별칭 release-gate), 루트는 OUT-FILE, 토큰은 release-gate 읽기 토큰.
# 확인: (1) 추론 서버 /readyz 가 release 도달 OK (2) 추론 서버와 같은 망에서 https://release-gate 가 release-gate 의 응답을 낸다(200/404 JSON, 토큰 없음·틀린 토큰 401)
#       (3) 음성: 사람 계정(승인자)의 GET /v1/releases/* 는 404, 토큰 없음·틀린 토큰은 401  (4) 서버 자신의 클라이언트가 HTTPS+추론 토큰으로 게이트웨이를 거쳐 release-gate 의 응답(NOT_FOUND)까지 받는다. 실제 번들 적재는 이 시험이 릴리스를 만들지 않아 확인하지 않는다(미확인)
# 바인드: 컨테이너가 host.docker.internal(host-gateway)로 호스트 게시 포트에 닿아야 한다. 127.0.0.1 -> docker 기본 브리지 게이트웨이 주소 -> 0.0.0.0 순으로 시도하고, 닿는 가장 좁은 것을 쓴다.
#   넓은 쪽으로 올라가면 사유를 출력한다. 열려 있는 것은 시험이 도는 동안뿐이다(trap 이 프로젝트를 지운다). 호스트 포트는 Docker 가 배정한다(이 스크립트가 고르지 않는다; 임시 레지스트리만 registry.sh 방식).
# 만드는 자원은 모두 deploy-e2e-loc 접두사다. 끝나면 지운다. 표준 docker 만 쓴다.
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 동작한다
source "$(dirname "$0")/lib.sh"
KEEP=0; REBUILD=0; CLEAN=0
for x in "$@"; do case "$x" in
  --keep) KEEP=1;; --rebuild) REBUILD=1;; --clean) CLEAN=1;;
  -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//' >&2; echo "알 수 없는 인자: $x" >&2; exit 2;; esac; done
detect_docker
P=deploy-e2e-loc; INF=deploy-e2e-loc-inf; REGP=deploy-e2e-loc-reg
W="$DEPLOY_ROOT/state/loc-test"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT="$P" DEPLOY_SKIP_DOCTOR=1
export REGISTRY_PROJECT="$REGP" REGISTRY_HOST_BIND="${LOC_REGISTRY_BIND:-127.0.0.1}" REGISTRY_HOST_PORT=
export SECRETS_DIR="$W/secrets" GATEWAY_PORT= GATEWAY_TLS_PORT=
# 왜 시험 호스트 이름을 넣는가: 추론 서버는 https://host.docker.internal:<포트> 로 부르고, 게이트웨이 인증서는 사이트 이름(GATEWAY_HOSTS)에 든 이름으로만 발급된다. 검증을 끄지 않는다
export GATEWAY_HOSTS="localhost:8443, host.docker.internal:8443"   # 첫 이름이 사람 화면의 공개 주소(Keycloak 발급자·로그인 쿠키)다: 시험 호스트가 풀 수 있는 localhost 를 앞에 둔다. 컨테이너 쪽 호출자는 host.docker.internal 로 부른다

cleanup() {
  echo "== 정리 ($P, $INF, $REGP, state/loc-test)"
  "$DOCKER" rm -f "$P-probe" >/dev/null 2>&1 || true
  "$DOCKER" compose -p "$P" --profile jobs --profile local-inference down -v --remove-orphans >/dev/null 2>&1 || true
  "$DOCKER" compose -p "$INF" down -v --remove-orphans >/dev/null 2>&1 || true
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1 || true
  [ "$W" = "$DEPLOY_ROOT/state/loc-test" ] && rm -rf "$W"
  echo "남은 자원:"; for q in "$P" "$INF" "$REGP"; do "$DOCKER" ps -a --filter "label=com.docker.compose.project=$q" --format '  컨테이너 {{.Names}}'; "$DOCKER" volume ls --filter "label=com.docker.compose.project=$q" --format '  볼륨 {{.Name}}'; done
}
if [ $CLEAN = 1 ]; then cleanup; exit 0; fi
[ -d "$W" ] && die "이전 시험 상태가 남아 있다 ($W). scripts/test-inference-location.sh --clean"
[ $KEEP = 1 ] || trap cleanup EXIT

PASS=0; FAIL=0
chk() { # chk <설명> <명령...>
  local d=$1; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  [PASS] $d"; else FAIL=$((FAIL+1)); echo "  [FAIL] $d"; fi
}
bail() { echo "중단: $*" >&2; exit 1; }

# 왜 doctor 를 부르지 않는가: doctor 는 빌드·전체 E2E 환경(형제 리포, 호스트 가상환경)을 점검한다. 이 시험은 이미 빌드된 이미지와 docker 만 쓴다(데몬은 lib.sh 의 detect_docker 가 본다)
mkdir -p "$W"
have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(grep -vc '^model-serving-gpu ' "$DEPLOY_ROOT/build/images.env")" -ge 8 ] && while read -r n img _; do [ "$n" = model-serving-gpu ] && continue; "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
if [ $REBUILD = 1 ] || ! have_images; then echo "== 이미지 빌드(현재 HEAD)"; bash "$DEPLOY_ROOT/scripts/build-images.sh" || bail "이미지 빌드 실패"; fi
grep -E '^[A-Z0-9_]+_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
echo "== 임시 레지스트리·게시·비밀"
bash "$DEPLOY_ROOT/scripts/registry.sh" up || bail "레지스트리 기동 실패 (데몬이 닿지 못하면 LOC_REGISTRY_BIND=0.0.0.0 으로 다시)"
bash "$DEPLOY_ROOT/scripts/publish-images.sh" || bail "게시 실패"
# --test-fixtures: 사람 계정 음성 확인에 시험 승인자 계정(trainer-e2e)이 필요하다. 이 비밀 폴더는 시험용이고(.test-fixtures 표시) 시험이 끝나면 지운다
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null || bail "비밀 생성 실패"

UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_LOCK")
cp "$SECRETS_DIR/tokens/inference-survey-service" "$W/inference-token"; chmod 640 "$W/inference-token"
export INFERENCE_TOKEN_FILE="$W/inference-token"
INF_IMAGE=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a; echo "$DEPLOY_REGISTRY/openit/model-serving@$MODEL_SERVING_DIGEST" )
BRIDGE_GW=$("$DOCKER" network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null | tr -d '\r')
PLACEHOLDER="https://host.docker.internal:1"   # 서버가 뜨기 전 자리표시 주소(아무 포트도 열지 않는다). 서버가 뜬 뒤 실제 주소로 바꿔 survey-service 만 다시 만든다
# 컨테이너(서버·호출자와 같은 위치)에서 host.docker.internal 로 닿는지. 인자: URL [CA 파일]
reach() {
  "$DOCKER" run --rm --name "$P-probe" --add-host host.docker.internal:host-gateway ${2:+-v "$2:/ca.crt:ro" -e SSL_CERT_FILE=/ca.crt} "$UTIL" python -c "import sys,json,urllib.request;b=urllib.request.urlopen(sys.argv[1],timeout=5).read().decode(); assert b.strip().startswith('ok') or json.loads(b).get('status')=='ok', b[:80]" "$1" >/dev/null 2>&1
}
inf_compose() { ( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
  # 이 변수들은 "다른 호스트" 쪽 compose 의 환경이다(제품 쪽에는 없다). fake 백엔드는 INFERENCE_ALLOW_FAKE=1 일 때만 시작한다(시험 전용 표시, model-runtime ADR 0009)
  INFERENCE_IMAGE="$INF_IMAGE" INFERENCE_TOKENS_FILE="$SECRETS_DIR/tokens/model-runtime-tokens" INFERENCE_RELEASE_TOKEN_FILE="$SECRETS_DIR/tokens/gate-read-model-serving" \
  INFERENCE_PKI_ROOT_FILE="$W/pki/root_ca.crt" INFERENCE_STEP_CA_URL="https://host.docker.internal:$SCP" INFERENCE_TLS_NAME=host.docker.internal INFERENCE_GATEWAY_IMAGE="$SC_IMG" INFERENCE_EXPOSURE_FILE="${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}/model-serving/exposure.json" INFERENCE_STEP_IMAGE="$STEP_IMG" INFERENCE_PAUSE_IMAGE="$PAUSE_IMG" INFERENCE_TLS_TOKEN_FILE="$W/tls.ott" \
  INFERENCE_CA_FILE="$W/pki/root_ca.crt" INFERENCE_RELEASE_NETWORK="${P}_inference-in" INFERENCE_BACKEND=fake INFERENCE_ALLOW_FAKE=1 INFERENCE_PORT= INFERENCE_BIND=$BIND \
    "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" -f "$DEPLOY_ROOT/compose.inference.samehost.yaml" "$@" ); }

PAUSE_IMG=$(sed -n 's/^PAUSE_IMAGE=//p' "$DEPLOY_LOCK"); STEP_IMG=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a; echo "$DEPLOY_REGISTRY/openit/step-ca@$STEP_CA_DIGEST" ); SC_IMG=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a; echo "$DEPLOY_REGISTRY/openit/area-gateway@$AREA_GATEWAY_DIGEST" )
# 빈 포트(고정 포트 금지). 확인은 기본 망에서 실제로 게시해 본다: --network none 의 -p 는 게시를 하지 않아(Moby null 드라이버) 확인이 되지 않는다(2026-11-07 교차검증). 안팎 포트가 같아야 토큰 audience 가 맞는다(compose.step-ca-publish.yaml). 호스트 쪽 제외 포트 범위(WSL/Windows)에 걸리면 Docker 가 게시를 거부하므로(측정함) 실제로 게시해 보고 고른다
SCP=""
for _try in 1 2 3 4 5 6 7 8; do
  _p=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
  if "$DOCKER" run --rm -p "127.0.0.1:$_p:$_p" "$UTIL" true >/dev/null 2>&1; then SCP=$_p; break; fi
done
[ -n "$SCP" ] || bail "게시할 수 있는 빈 포트를 찾지 못했다"
export STEP_CA_PORT=$SCP STEP_CA_DNS_NAMES=host.docker.internal COMPOSE_EXTRA="${COMPOSE_EXTRA:-} $DEPLOY_ROOT/compose.step-ca-publish.yaml"
mkdir -p "$W/pki"
GWP=""
for _try in 1 2 3 4 5 6 7 8; do
  _p=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
  if "$DOCKER" run --rm -p "127.0.0.1:$_p:$_p" "$UTIL" true >/dev/null 2>&1; then GWP=$_p; break; fi
done
[ -n "$GWP" ] || bail "게이트웨이에 게시할 수 있는 빈 포트를 찾지 못했다"
export GATEWAY_TLS_PORT=$GWP
# 사람 인증(U82, ADR 0057): Keycloak 의 발급자와 oauth2-proxy 의 콜백은 밖에서 보이는 주소(첫 호스트 이름 + 밖에 보이는 포트)로 정해진다. 호스트 포트를 시험이 먼저 정하므로 그 포트를 밖에 보이는 포트로 준다
export GATEWAY_PUBLIC_TLS_PORT=$GATEWAY_TLS_PORT
# 한 줄의 export 안에서는 $(...) 가 앞의 대입보다 먼저 풀린다(e2e.sh 3차 E2E 와 같은 결함). 그래서 따로 쓴다
export GATEWAY_PUBLIC_URL="$(gateway_public_url)"
OK=0
for BIND in 127.0.0.1 $BRIDGE_GW 0.0.0.0; do
  [ -n "$BIND" ] || continue
  [ "$BIND" = 127.0.0.1 ] || echo "== 사유: 컨테이너가 host.docker.internal 로 더 좁은 바인드의 게시 포트에 닿지 못했다. 시험 동안만 $BIND 로 게시한다"
  "$DOCKER" compose -p "$INF" down -v --remove-orphans >/dev/null 2>&1 || true
  echo "== (가) 제품 기동(바인드 $BIND): 운영 모드, model-serving 끔, 외부 추론 서버 자리표시 주소"
  STEP_CA_BIND=$BIND GATEWAY_BIND=$BIND bash "$DEPLOY_ROOT/scripts/up.sh" "$P" --external-inference "$PLACEHOLDER" || bail "제품 기동 실패"
  GWPORT=$(port_of "$P-gateway-1" 8443)
  [ -n "$GWPORT" ] || bail "게이트웨이 TLS 호스트 포트를 읽지 못했다 (바인드 $BIND)"
  bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$P" "$W/gateway-ca.crt" || bail "게이트웨이 CA 를 꺼내지 못했다"
  if ! reach "https://host.docker.internal:$GWPORT/healthz" "$W/gateway-ca.crt"; then echo "  컨테이너에서 게이트웨이 https://host.docker.internal:$GWPORT 에 닿지 못했다 (바인드 $BIND)"; continue; fi   # body-judged: reach 가 본문 status/ok 를 판정한다
  "$DOCKER" run --rm -v "${P}_pki-root:/r:ro" "$UTIL" cat /r/root_ca.crt > "$W/pki/root_ca.crt" || bail "step-ca 루트를 꺼내지 못했다"
  # 지휘 쪽: 이 서버 이름(host.docker.internal)의 일회용 토큰을 발급해 파일로 준다(비밀번호는 이 컨테이너만 읽는다)
  step_issue_token "$STEP_IMG" host.docker.internal "https://host.docker.internal:$SCP" "$W/pki" "$SECRETS_DIR/tokens/step-ca-password" "$W/tls.ott" --add-host host.docker.internal:host-gateway || bail "일회용 토큰을 발급하지 못했다"
  echo "== (나) 다른 호스트: 별도 프로젝트 $INF, compose.inference.yaml 하나 (바인드 $BIND, 포트는 Docker 배정)"
  inf_compose up -d --wait || { echo "  추론 서버가 준비되지 않았다 (바인드 $BIND)"; "$DOCKER" logs --tail 20 "$INF-model-serving-1" 2>&1 | sed 's/^/    /'; bail "추론 서버 기동 실패"; }
  IPORT=$(port_of "$INF-model-serving-net-1" 443)
  [ -n "$IPORT" ] || bail "추론 서버 호스트 포트를 읽지 못했다"
  if reach "https://host.docker.internal:$IPORT/healthz" "$W/pki/root_ca.crt"; then OK=1; break; fi   # body-judged: reach 가 본문 status/ok 를 판정한다
  echo "  컨테이너에서 추론 서버 host.docker.internal:$IPORT 에 닿지 못했다 (바인드 $BIND)"
done
[ $OK = 1 ] || bail "컨테이너가 호스트에 게시된 게이트웨이·서버에 닿지 못했다(방화벽·제외 포트 범위 확인)"
echo "  바인드 $BIND 로 게이트웨이 https://host.docker.internal:$GWPORT, 추론 서버 :$IPORT 에 컨테이너에서 닿는다"

echo "== survey-service 를 실제 서버 주소로 다시 만든다(--external-inference https://host.docker.internal:$IPORT)"
GATEWAY_BIND=$BIND bash "$DEPLOY_ROOT/scripts/up.sh" "$P" --external-inference "https://host.docker.internal:$IPORT" || bail "제품 재기동 실패"
chk "추론 서버가 별도 프로젝트($INF)의 컨테이너다" test -n "$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$INF" --filter "name=model-serving")"
chk "제품에 model-serving 컨테이너가 없다(프로필로 꺼짐)" test -z "$("$DOCKER" ps -a -q --filter "name=^$P-model-serving")"
# 운영 compose 에 release-gate 호스트 게시가 없다(시험용 문이 없다)
chk "release-gate 는 호스트에 게시되지 않는다" test -z "$("$DOCKER" port "$P-release-gate-1" 2>/dev/null)"

# ---- 확인. 호스트에서 게이트웨이 TLS 포트를 CA 로 검증해 부른다(--resolve: 인증서 이름 host.docker.internal 을 게시 주소로)
CA="$W/gateway-ca.crt"; GW="https://host.docker.internal:$GWPORT"; RES="host.docker.internal:$GWPORT:$BIND"
[ "$BIND" = 0.0.0.0 ] && RES="host.docker.internal:$GWPORT:127.0.0.1"
gw_code() { # gw_code <경로> [curl 인자...] -> HTTP 코드 (본문은 $W/body)
  local path=$1; shift
  curl -sS --max-time 20 --cacert "$CA" --resolve "$RES" -o "$W/body" -w '%{http_code}' "$@" "$GW$path" 2>/dev/null
}
is() { [ "$(eval "$1")" = "$2" ]; }

# 추론 서버의 사이드카 인증서는 이름(host.docker.internal) 하나다: IP 로 부르면 SNI 가 맞는 사이트가 없어 TLS 가 끊긴다(측정함: tlsv1 alert internal error). 이름으로 부르고 --resolve 로 게시 주소를 준다
MS_HOST=$([ "$BIND" = 0.0.0.0 ] && echo 127.0.0.1 || echo "$BIND")
MSURL="https://host.docker.internal:$IPORT"; MSRES="host.docker.internal:$IPORT:$MS_HOST"
echo "== 1. 추론 서버 /readyz: release 도달"
READY=$(curl -sS --max-time 10 "$MSURL/readyz" --resolve "$MSRES" --cacert "$W/pki/root_ca.crt" 2>&1 || true)
echo "  /readyz: $(echo "$READY" | cut -c1-300)"
chk "추론 서버가 게이트웨이(HTTPS, 신뢰 CA)로 release 에 닿는다 (/readyz 에 release 도달 실패 사유가 없다)" bash -c 'echo "$1" | python3 -c "import json,sys;d=json.load(sys.stdin);t=json.dumps(d,ensure_ascii=False);sys.exit(1 if \"닿지 못한다\" in t else 0)"' _ "$READY"

echo "== 2. 추론 서버 길: release-gate 영역 게이트웨이로 바로(R1.5, 외부 망 inference-in 의 별칭 release-gate)"
RGTOK=$(tr -d '\r\n' < "$SECRETS_DIR/tokens/gate-read-model-serving")
rg_code() { # rg_code <경로> [토큰] -> HTTP 코드(본문은 $W/body). 추론 서버와 같은 망(${P}_inference-in)의 컨테이너에서 https://release-gate 를 OUT-FILE 루트로 검증해 부른다
  "$DOCKER" run --rm --network "${P}_inference-in" -v "$W/pki/root_ca.crt:/root_ca.crt:ro" -e SSL_CERT_FILE=/root_ca.crt -e RGTOK="${2:-}" "$UTIL" python -c "
import os, sys, urllib.request, urllib.error
r = urllib.request.Request('https://release-gate' + sys.argv[1])
if os.environ.get('RGTOK'): r.add_header('Authorization', 'Bearer ' + os.environ['RGTOK'])
try: resp = urllib.request.urlopen(r, timeout=15); code, body = resp.status, resp.read()
except urllib.error.HTTPError as e: code, body = e.code, e.read()
open('/dev/stderr', 'wb').write(body[:2000]); print(code)" "$1" 2>"$W/body" | tail -1
}
C=$(rg_code /v1/active-pointer "$RGTOK"); echo "  GET /v1/active-pointer (release-gate 읽기 토큰) -> $C"
chk "active-pointer 가 release-gate 에서 온다(200, 또는 활성 릴리스가 없으면 release-gate 의 404 JSON)" bash -c '[ "$1" = 200 ] || { [ "$1" = 404 ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$2"; }' _ "$C" "$W/body"
C=$(rg_code /v1/releases/does-not-exist "$RGTOK"); echo "  GET /v1/releases/does-not-exist -> $C"
chk "릴리스 조회가 release-gate 에서 온다(404 이고 본문이 JSON)" bash -c '[ "$1" = 404 ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$2"' _ "$C" "$W/body"
C=$(rg_code /v1/releases/does-not-exist/bundle "$RGTOK"); echo "  GET /v1/releases/does-not-exist/bundle -> $C"
chk "번들 조회가 release-gate 에서 온다(404 JSON)" bash -c '[ "$1" = 404 ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$2"' _ "$C" "$W/body"
chk "토큰 없이는 release-gate 가 401 로 거절한다(받는 영역이 직접 대조)" is "rg_code /v1/active-pointer" 401
chk "틀린 토큰은 401" is "rg_code /v1/active-pointer wrong" 401

echo "== 3. 음성 확인"
# (ㄱ) 사람 세션: E2E 단계 5u·test-idp-smoke.sh 와 같은 OIDC 로그인 도우미(scripts/e2e_sandbox.py oidc_login: Keycloak 로그인 -> _openit_session 쿠키)로 승인자 계정 세션을 만든다
bash "$DEPLOY_ROOT/scripts/idp-test-users.sh" "$P" >/dev/null 2>&1 || bail "시험 사용자(Keycloak)를 만들지 못했다"
HCOOKIE=$(DEPLOY_ROOT="$DEPLOY_ROOT" "$DEPLOY_ROOT/.venv/bin/python" -W ignore - "$GATEWAY_PUBLIC_URL" "$CA" "$SECRETS_DIR/tokens/idp-test-trainer-e2e-password" <<'PY'
import os, socket, sys
sys.path.insert(0, os.path.join(os.environ["DEPLOY_ROOT"], "scripts"))
import e2e_sandbox as SB
base, ca, pwf = sys.argv[1:4]
jar = SB.oidc_login(base, "trainer-e2e", open(pwf).read().strip(), ca=ca)
print("; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("_openit_session")))
PY
) 2>"$W/oidc.err" || { tail -4 "$W/oidc.err" | sed "s/^/    /" >&2; echo "  로그인 대상 $GATEWAY_PUBLIC_URL, 게시 포트 $GWPORT, 컨테이너 상태:" >&2; "$DOCKER" ps -a --filter "label=com.docker.compose.project=$P" --format "    {{.Names}} {{.Status}}" 2>&1 | grep -E "gateway-1|oauth2-proxy-1|keycloak-1" >&2; "$DOCKER" logs --tail 5 "$P-gateway-1" 2>&1 | cut -c1-240 | sed "s/^/    gw: /" >&2; bail "승인자 OIDC 로그인에 실패했다"; }
[ -n "$HCOOKIE" ] || bail "승인자 세션 쿠키가 비었다"
chk "(ㄱ) 사람 계정(승인자)의 GET /v1/releases/{id} 는 404(공개 입구가 내보내지 않는다)" is "gw_code /v1/releases/does-not-exist -H 'Cookie: $HCOOKIE'" 404
chk "(ㄱ) 사람 계정(승인자)의 GET /v1/releases/{id}/bundle 은 404" is "gw_code /v1/releases/does-not-exist/bundle -H 'Cookie: $HCOOKIE'" 404
chk "(ㄴ) 공개 입구는 기계 토큰을 받지 않는다: 읽기 토큰을 붙여도 GET /v1/active-pointer 는 사람 인증 블록에 막혀 401 이다(3.4.7: 기계 호출자는 받는 영역으로 직접 간다)" is "gw_code /v1/active-pointer -H 'Authorization: Bearer $RGTOK'" 401
chk "(ㄴ) 토큰 없이 GET /v1/releases/{id}/bundle 도 404 (경로 자체가 없다)" is "gw_code /v1/releases/does-not-exist/bundle" 404
# (ㄷ) 학습 서버의 게시(I3 POST /v1/packages, 쓰기 역할 model-lab)도 공개 입구에는 경로가 없다(R3.23, ADR 0071). 토큰은 머리글 파일로 넘긴다(명령 줄·프로세스 목록에 값을 두지 않는다)
( umask 077; printf 'Authorization: Bearer %s\n' "$(tr -d '\r\n' < "$SECRETS_DIR/tokens/model-registry-write-model-lab")" > "$W/mrw.hdr" )
chk "(ㄷ) 공개 입구는 model-registry 쓰기 토큰의 POST /v1/packages 를 받지 않는다(401 또는 404: 기계 게시 경로 없음, R3.23)" bash -c 'c=$1; [ "$c" = 401 ] || [ "$c" = 404 ]' _ "$(gw_code /v1/packages -X POST -H 'Content-Type: application/x-tar' -H @"$W/mrw.hdr" --data-binary '')"
rm -f "$W/mrw.hdr"

echo "== 4. 추론 서버 자신의 클라이언트가 release-gate 영역 게이트웨이(HTTPS, 읽기 토큰)로 release-gate 까지 간다"
# 왜 없는 릴리스인가: 서버는 적재 신호(PUT /v1/releases/{id})를 받으면 계약 클라이언트로 GET /v1/releases/{id}(/bundle)를 한다. 릴리스를 만들려면 문항 세트·모델 패키지·승인·활성화가 필요한데
# 운영 compose 에 시험용 문 없이는 게이트웨이로 할 수 없다(릴리스 생성은 e2e.sh 단계 1~4 가 덮는다). 그래서 이 시험은 번들이 실제로 적재되는 것까지는 보지 않는다(미확인).
# 없는 ID 면 release-gate 의 404 가 서버의 FAILED(FAILED_PRECONDITION, "그 릴리스를 찾지 못했다")로 돌아온다. TLS 검증 실패·토큰 거부·경로 차단이면 다른 코드(UNAVAILABLE/PERMISSION_DENIED 등)가 나오므로 구별된다.
MS_TOK=$(sed 's/^[^=]*=//; s/,.*//' "$SECRETS_DIR/tokens/model-runtime-tokens" | tr -d '\r\n')
curl -sS --max-time 15 -X PUT -H "Authorization: Bearer $MS_TOK" "$MSURL/v1/releases/rel-loc-test-none" --resolve "$MSRES" --cacert "$W/pki/root_ca.crt" >/dev/null 2>&1
sleep 3
ST=$(curl -sS --max-time 10 -H "Authorization: Bearer $MS_TOK" "$MSURL/v1/releases/rel-loc-test-none" --resolve "$MSRES" --cacert "$W/pki/root_ca.crt" 2>&1)
echo "  서버의 상태 본문: $(echo "$ST" | cut -c1-600)"
echo "  서버의 상태: $(echo "$ST" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('state'), (d.get('error') or {}).get('code'), (d.get('error') or {}).get('details'))" 2>&1)"
chk "서버가 release-gate 의 '릴리스 없음'(404)을 받았다(FAILED, FAILED_PRECONDITION '그 릴리스를 찾지 못했다': release-gate 영역 게이트웨이 TLS·토큰·경로가 모두 통과, 전송 실패는 UNAVAILABLE 로 구별된다)" bash -c 'echo "$1" | python3 -c "import json,sys;d=json.load(sys.stdin);e=d[\"error\"];sys.exit(0 if d.get(\"state\")==\"FAILED\" and e[\"code\"]==\"FAILED_PRECONDITION\" and \"찾지 못했다\" in e[\"message\"] else 1)"' _ "$ST"
echo "  (미확인) 실제 번들 적재: 이 시험은 릴리스를 만들지 않는다. 활성 릴리스가 있는 환경에서는 docs/runbook.md 의 원격 추론 서버 절 확인 순서로 본다"
echo; echo "위치 독립 시험: PASS $PASS / FAIL $FAIL (게시 바인드 $BIND)"
[ $KEEP = 1 ] && echo "(--keep: 자원을 남겼다. 지우기: scripts/test-inference-location.sh --clean)"
[ $FAIL = 0 ]
