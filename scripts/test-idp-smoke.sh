#!/usr/bin/env bash
# 사람 인증(U82, head ADR 0014, deploy ADR 0057)을 진짜 Keycloak + oauth2-proxy + Caddy 로 확인하는 스모크 시험. 사용: bash scripts/test-idp-smoke.sh
# 임시 프로젝트(deploy-idpsmoke-*)에서 postgres, keycloak, oauth2-proxy, gateway 만 띄운다(이웃 서비스 없음: 인증 통과한 요청은 상류 부재로 503/504 가 된다). 끝나면 지운다.
# 확인(head ADR 0014 시험 목록): realm 가져오기 -> 가입 신청 -> 승인 전 403 ACCOUNT_PENDING_APPROVAL -> admin 이 그룹 부여 -> 다시 로그인 -> 역할별 허용·거부 -> 로그아웃 -> 로그인 이벤트 기록.
# 값(암호·토큰)은 출력하지 않는다. Docker 필요(이미지는 locks/images.lock 의 digest: 처음에는 받는 시간이 든다).
set -uo pipefail
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/testlib.sh"
ID=$$; P=deploy-idpsmoke-$ID; W="$DEPLOY_ROOT/state/idpsmoke-$ID"; mkdir -p "$W"
export DEPLOY_PROJECT=$P SECRETS_DIR="$W/secrets" DEPLOY_REGISTRY_ENV="$W/registry.env"
echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$DEPLOY_REGISTRY_ENV"; test_lock_copy "$W/images.lock"; export DEPLOY_LOCK="$W/images.lock"
cleanup() { [ "${KEEP:-0}" = 1 ] && { echo "KEEP=1: 프로젝트 $P 와 $W 를 남겼다"; return; }; dc "$P" down -v --remove-orphans >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_LOCK")
fp() { local p _t; for _t in 1 2 3 4 5 6 7 8; do p=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'); "$DOCKER" run --rm -p "127.0.0.1:$p:1" "$UTIL" true >/dev/null 2>&1 && { echo $p; return 0; }; done; return 1; }
export GATEWAY_TLS_PORT=$(fp) GATEWAY_PORT= GATEWAY_BIND=127.0.0.1; export GATEWAY_PUBLIC_TLS_PORT=$GATEWAY_TLS_PORT
export GATEWAY_PUBLIC_URL=$(gateway_public_url) GATEWAY_HOST_NAMES=$(gateway_host_names)   # lib.sh 를 source 한 뒤에 포트를 정했으므로 다시 계산한다
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null 2>&1 || { echo "gen-secrets 실패"; exit 1; }
V="${P}_gateway-data"; "$DOCKER" volume create --label "com.docker.compose.project=$P" --label "com.docker.compose.volume=gateway-data" "$V" >/dev/null
"$DOCKER" run --rm --network none --user 0 --cap-drop ALL --cap-add CHOWN -v "$V:/data" "$UTIL" chown 10001:10001 /data >/dev/null
bash "$DEPLOY_ROOT/scripts/gen-keycloak-realm.sh" "$SECRETS_DIR/keycloak-realm.json" >/dev/null
FAILS=0; N=0
ok() { N=$((N+1)); local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-220)"; FAILS=$((FAILS+1)); fi; }
echo "== 기동 (postgres -> keycloak -> oauth2-proxy -> gateway)"
dc "$P" up -d --wait --wait-timeout 120 postgres >"$W/up1.log" 2>&1; ok "postgres healthy" test -n "$(pg_container "$P")"
dc "$P" up -d --wait --wait-timeout 300 --no-deps keycloak keycloak-cert keycloak-tls >"$W/up2.log" 2>&1; ok "keycloak healthy (realm openit 가져오기 포함)" bash -c "dc() { :; }; docker inspect --format '{{.State.Health.Status}}' ${P}-keycloak-1 | grep -q healthy"
dc "$P" up -d --wait --wait-timeout 180 --no-deps oauth2-proxy oauth2-proxy-cert oauth2-proxy-tls gateway >"$W/up3.log" 2>&1; ok "oauth2-proxy·gateway 기동" bash -c "docker inspect --format '{{.State.Running}}' ${P}-oauth2-proxy-1 ${P}-gateway-1 | grep -vc true | grep -q '^0$'"
ok "keycloak 로그에 암호·비밀 값이 없다" bash -c "! docker logs ${P}-keycloak-1 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/db-keycloak-password)\" && ! docker logs ${P}-keycloak-1 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/oauth2-proxy-client-secret)\""
ok "keycloak 프로세스의 /proc/1/environ 에도 비밀 값이 없다(설정 파일로 받는다, D84)" bash -c "! docker exec ${P}-keycloak-1 cat /proc/1/environ | tr '\\0' '\\n' | grep -qF \"\$(cat $SECRETS_DIR/tokens/db-keycloak-password)\""
ok "keycloak·oauth2-proxy 컨테이너 환경 변수에 비밀 값이 없다(*_FILE 경로만)" bash -c "e=\$(docker inspect ${P}-keycloak-1 ${P}-oauth2-proxy-1 --format '{{range .Config.Env}}{{println .}}{{end}}'); ! grep -qF \"\$(cat $SECRETS_DIR/tokens/db-keycloak-password)\" <<<\"\$e\" && ! grep -qF \"\$(cat $SECRETS_DIR/tokens/oauth2-proxy-client-secret)\" <<<\"\$e\" && ! grep -qF \"\$(cat $SECRETS_DIR/tokens/oauth2-proxy-cookie-secret)\" <<<\"\$e\""
bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$P" "$W/gateway-ca.crt" >/dev/null 2>&1 || { echo "gateway CA 를 가져오지 못했다"; exit 1; }
ok "시험 사용자를 Keycloak 에 만든다(운영 입구: kcadm)" bash "$DEPLOY_ROOT/scripts/idp-test-users.sh" "$P"
echo "== 로그인·역할 (게이트웨이 경유)"
export W P
"$DEPLOY_PY" -W ignore - <<'PY' || FAILS=$((FAILS+1))
import json, os, sys, pathlib, urllib.request, urllib.parse, urllib.error, ssl, re, html, subprocess
sys.path.insert(0, os.path.join(os.environ["DEPLOY_ROOT"] if "DEPLOY_ROOT" in os.environ else ".", "scripts"))
sys.path.insert(0, str(pathlib.Path(os.environ["W"]).parent.parent / "scripts"))
import e2e_sandbox as SB
W = pathlib.Path(os.environ["W"]); P = os.environ["P"]
SB.init(project=P, secrets=str(W / "secrets"), gw_ca=str(W / "gateway-ca.crt"))
fails = 0
def chk(name, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f" :: {detail}")); fails += 0 if cond else 1
base = SB.gw_url(human=True)
def human(method, path, account=None, **kw):
    return SB.gw_request(method, path, account=account, **kw)
# 인증 없음
st, h, b = SB.gw_request("GET", "/v1/staff/alerts"); chk("인증 없는 API 는 401 + Bearer", st == 401 and h.get("www-authenticate", "").startswith("Bearer"), st)
st, h, b = SB.gw_request("GET", "/staff/"); chk("인증 없는 화면은 로그인(/oauth2/start)으로 302", st == 302 and h.get("location", "").startswith("/oauth2/start"), (st, h.get("location")))
# 로그인한 역할별
st, h, b = human("GET", "/v1/staff/alerts", "staff-e2e"); chk("staff 로그인 -> 직원 API 통과(상류 없음 503/504)", st in (503, 504), st)
st, h, b = human("POST", "/v1/activate", "staff-e2e"); chk("staff -> operator 경로 403", st == 403, st)
st, h, b = human("POST", "/v1/activate", "operator-e2e"); chk("operator -> 활성화 통과", st in (503, 504), st)
st, h, b = human("GET", "/v1/cases", "multi-e2e"); chk("한 사람이 역할 둘(reviewer, clinician): reviewer 경로 통과", st in (503, 504), st)
st, h, b = human("GET", "/v1/results", "multi-e2e"); chk("같은 사람: clinician 경로도 통과", st in (503, 504), st)
st, h, b = human("GET", "/v1/staff/alerts", "clinician-e2e"); chk("clinician -> 직원 API 403", st == 403, st)
st, h, b = human("GET", "/v1/staff/push-config", "clinician-e2e"); chk("clinician -> 푸시 설정 통과(U92)", st in (503, 504), st)
st, h, b = human("GET", "/v1/staff/alerts", "pending-e2e"); chk("승인 대기(그룹 없음) -> 403 ACCOUNT_PENDING_APPROVAL", st == 403 and b"ACCOUNT_PENDING_APPROVAL" in b, (st, b[:100]))
# userinfo (admin-console 이 읽는다)
st, h, b = human("GET", "/oauth2/userinfo", "multi-e2e"); ui = json.loads(b) if st == 200 else {}
chk("/oauth2/userinfo: 사용자 이름(preferredUsername)", st == 200 and ui.get("preferredUsername") == "multi-e2e", (st, ui))
chk("/oauth2/userinfo 의 groups 가 그룹 이름 목록", sorted(ui.get("groups", [])) == ["clinician", "reviewer"], ui)
# 로그아웃: rd 가 상대 경로(Keycloak 로그아웃)를 막지 않는다
rd = "/auth/realms/openit/protocol/openid-connect/logout?client_id=openit-gateway&post_logout_redirect_uri=" + urllib.parse.quote(base + "/", safe="")
st, h, b = human("GET", "/oauth2/sign_out?rd=" + urllib.parse.quote(rd, safe=""), "staff-e2e")
chk("/oauth2/sign_out?rd=<Keycloak 로그아웃 상대 경로> 가 막히지 않는다", st in (302, 303) and "/auth/realms/openit/protocol/openid-connect/logout" in h.get("location", ""), (st, h.get("location")))
SB.forget_session("staff-e2e")
# Keycloak 은 /auth/ 로, master realm 은 닫힘, 관리 화면은 realm openit
st, h, b = SB.gw_request("GET", "/auth/realms/openit/.well-known/openid-configuration")
cfg = json.loads(b) if st == 200 else {}
chk("Keycloak discovery 의 발급자는 밖에 보이는 주소", cfg.get("issuer") == base + "/auth/realms/openit", cfg.get("issuer"))
st, h, b = SB.gw_request("GET", "/auth/realms/master/.well-known/openid-configuration"); chk("master realm 은 밖에 닫혀 있다(404)", st == 404, st)
st, h, b = SB.gw_request("GET", "/auth/admin/openit/console/"); chk("realm openit 관리 화면이 열린다", st in (200, 302), st)
# 가입 신청 -> 승인 대기 -> admin 이 그룹 부여 -> 다시 로그인
def register(username, password):
    ctx = ssl.create_default_context(cafile=str(W / "gateway-ca.crt"))
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}), SB._NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    jar = {}
    def rq(method, url, data=None, headers=None):
        hh = dict(headers or {}); 
        if jar: hh["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        r = urllib.request.Request(url, data=data, method=method, headers=hh)
        try:
            with op.open(r, timeout=30) as resp: jar.update(SB._cookies_of(resp.headers)); return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e: jar.update(SB._cookies_of(e.headers)); return e.code, dict(e.headers), e.read().decode()
    url = base + "/oauth2/start?rd=/"
    for _ in range(6):
        st, hd, body = rq("GET", url); loc = hd.get("Location")
        if st in (301, 302, 303) and loc: url = urllib.parse.urljoin(url, loc); continue
        break
    m = re.search(r'href="([^"]*registration[^"]*)"', body)
    if not m: return False, "가입 링크가 없다"
    url = urllib.parse.urljoin(url, html.unescape(m.group(1)))
    st, hd, body = rq("GET", url)
    m = re.search(r'<form[^>]*id="kc-register-form"[^>]*action="([^"]+)"', body)
    if not m: return False, "가입 양식이 없다"
    form = urllib.parse.urlencode({"username": username, "email": f"{username}@test.invalid", "firstName": "New", "lastName": "User", "password": password, "password-confirm": password}).encode()
    st, hd, body = rq("POST", urllib.parse.urljoin(url, html.unescape(m.group(1))), data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
    for _ in range(10):
        loc = hd.get("Location")
        if st in (301, 302, 303) and loc: url = urllib.parse.urljoin(url, loc); st, hd, body = rq("GET", url); continue
        break
    return "_openit_session" in jar, (st, jar.keys())
newpw = "Newuser-pw-" + os.urandom(6).hex()
ok_, why = register("newbie-e2e", newpw); chk("가입 신청(자가 등록)이 되고 바로 로그인된다", ok_, why)
jar = SB.oidc_login(base, "newbie-e2e", newpw, ca=str(W / "gateway-ca.crt")) if ok_ else {}
cookie = "; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("_openit_session"))
st, h, b = SB.gw_request("GET", "/v1/staff/alerts", headers={"Cookie": cookie}); chk("가입 직후(그룹 없음)는 403 ACCOUNT_PENDING_APPROVAL", st == 403 and b"ACCOUNT_PENDING_APPROVAL" in b, (st, b[:80]))
def kcadm(*a):
    r = subprocess.run(["bash", "-c", 'source "$1/scripts/lib.sh" && shift && dc "$@"', "dc", os.environ.get("DEPLOY_ROOT", str(pathlib.Path(__file__).resolve().parent) if False else "."), P, "exec", "-T", "keycloak", "/opt/keycloak/bin/kcadm.sh", *a, "--config", "/tmp/kcadm.config"], capture_output=True, text=True)
    return r.returncode, r.stdout
rc, out = kcadm("get", "users", "-r", "openit", "-q", "username=newbie-e2e", "--fields", "id", "--format", "csv", "--noquotes"); uid = out.strip()
rc, out = kcadm("get", "groups", "-r", "openit", "-q", "search=staff", "--fields", "id,name", "--format", "csv", "--noquotes"); gid = [l.split(",")[0] for l in out.splitlines() if l.strip().endswith(",staff")][0]
rc, _ = kcadm("update", f"users/{uid}/groups/{gid}", "-r", "openit", "-s", "realm=openit", "-s", f"userId={uid}", "-s", f"groupId={gid}", "-n"); chk("admin 이 staff 그룹을 부여한다(승인)", rc == 0)
jar = SB.oidc_login(base, "newbie-e2e", newpw, ca=str(W / "gateway-ca.crt"))
cookie = "; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("_openit_session"))
st, h, b = SB.gw_request("GET", "/v1/staff/alerts", headers={"Cookie": cookie}); chk("승인 뒤 다시 로그인하면 직원 API 가 통과한다", st in (503, 504), (st, b[:80]))
# 로그인 이벤트 기록
rc, out = kcadm("get", "events", "-r", "openit", "-q", "type=LOGIN", "-q", "max=5"); chk("로그인 이벤트가 기록된다(realm 이벤트 저장)", rc == 0 and '"type" : "LOGIN"' in out, out[:120])
rc, out = kcadm("get", "realms/openit", "--fields", "eventsExpiration"); chk("로그인 기록 보존 365일(31536000초)", "31536000" in out, out)
print(f"  Python 확인 {fails} 건 실패")
sys.exit(1 if fails else 0)
PY
echo; [ $FAILS = 0 ] && echo "통과: IdP 스모크 시험" || { echo "실패: $FAILS건"; exit 1; }
