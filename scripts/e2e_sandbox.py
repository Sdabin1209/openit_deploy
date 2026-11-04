#!/usr/bin/env python3
"""E2E 드라이버(e2e_steps.py)가 제품에 닿는 유일한 접근 계층(샌드박스, docs/adr/0050-e2e-sandbox.md).

드라이버는 호스트(= 운영자 PC 역할)에서 돌고 제품(compose.yaml)에는 시험용 문이 없다. 허용되는 접근은 셋뿐이다.
  (a) 게이트웨이 호스트 포트(HTTPS, 게이트웨이 CA 만 신뢰): gw_url, gw_request, gw_client
  (b) 제품 네트워크 안에서 제품의 컨테이너를 쓰는 것: exec_in, exec_py, run_job, readyz, psql, logs
  (c) 다른 호스트 역할인 추론 서버(compose.inference.yaml 을 별도 프로젝트로 띄운 것): inference_url
내부 서비스의 호스트 포트를 부르는 코드는 이 모듈에 없다(없어야 한다: scripts/test_compose_no_test_doors.py 가 compose 쪽을, 단계 코드는 리뷰가 본다).
전역 상태는 init() 이 채우는 설정 하나뿐이다. 비밀(계정 암호·토큰)은 파일에서 읽어 헤더에만 쓰고 출력·로그에 남기지 않는다.
"""
from __future__ import annotations

import json
import json as _json   # gw_request 의 인자 이름 json 이 모듈을 가리므로 별칭을 둔다(시그니처가 고정이다)
import os
import pathlib
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

_C: dict[str, Any] = {}   # init() 이 채운다: project, secrets, gw_ca, docker, inference_project, root, run(시험에서 subprocess.run 대체), _gw_port(캐시)


def init(**kw) -> None:
    """project(필수), secrets(필수: 비밀 폴더), gw_ca(게이트웨이 CA 루트 파일), docker, inference_project(추론 서버 프로젝트 이름), root(deploy 루트), run(시험용 실행기)."""
    # 왜 키를 검사하나: 단계 코드가 철자를 틀리면 조용히 무시되지 말고 첫 호출에서 드러나야 한다
    unknown = set(kw) - {"project", "secrets", "gw_ca", "docker", "inference_project", "root", "run"}
    if unknown:
        raise TypeError(f"init 이 모르는 인자: {sorted(unknown)}")
    if not kw.get("project") or not kw.get("secrets"):
        raise TypeError("init 에는 project 와 secrets 가 필요하다")
    root = kw.get("root") or pathlib.Path(__file__).resolve().parents[1]
    _C.clear()
    _C.update({"docker": "docker", "inference_project": "", "gw_ca": "", "run": subprocess.run, **kw})
    if not _C["inference_project"]:
        _C["inference_project"] = f"{_C['project']}-inf"   # 왜 기본값: e2e.sh 가 추론 서버를 <P>-inf 로 띄운다. 단계 코드가 이름을 따로 알 필요가 없다
    _C["root"] = pathlib.Path(root)
    _C["secrets"] = pathlib.Path(_C["secrets"])
    if _C["gw_ca"]:
        # 왜 환경 변수인가: boundary_contracts 클라이언트(HttpClientBase)는 CA 인자가 없고 기본 SSL 문맥을 쓴다. 기본 문맥은 OpenSSL 의 SSL_CERT_FILE 을 읽으므로
        # 프로세스에 그 값을 두면 클라이언트를 고치지 않고 게이트웨이 CA 로 검증된다(검증을 끄지 않는다). 이 프로세스는 게이트웨이만 부르므로 부작용이 없다.
        os.environ["SSL_CERT_FILE"] = str(_C["gw_ca"])


def _need(key: str):
    if key not in _C or _C[key] in ("", None):
        raise RuntimeError(f"e2e_sandbox.init({key}=...) 가 필요하다")
    return _C[key]


def _run(cmd: list[str], *, input: Optional[str] = None, timeout: float = 60, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOCKER": _C.get("docker", "docker")}
    r = _C.get("run", subprocess.run)(cmd, capture_output=True, text=True, input=input, timeout=timeout, env=env)
    if check and r.returncode != 0:
        # 왜 stderr 끝만: 오류 원인은 보이되 명령 입력(코드·SQL)과 환경은 싣지 않는다
        raise RuntimeError(f"{' '.join(cmd[-3:])[:80]} 실패({r.returncode}): {(r.stderr or r.stdout or '')[-500:]}")
    return r


def _dc(*args: str) -> list[str]:
    """제품 프로젝트에 대한 `docker compose -p P ...`. 파일·env-file 조립은 scripts/lib.sh 의 dc 하나를 쓴다(스크립트들과 같은 규칙, 복제하지 않는다)."""
    root = str(_need("root"))
    return ["bash", "-c", 'source "$1/scripts/lib.sh" && shift && dc "$@"', "dc", root, _need("project"), *args]


# ---- (a) 게이트웨이 ----
def _docker_port(container_or_none: Optional[str], service: str, cport: str) -> Optional[str]:
    # 왜 docker port: 호스트 포트는 Docker 가 배정한다(고정 포트 금지, CLAUDE.md). 멈췄다 다시 뜨면 바뀔 수 있어 필요할 때 묻는다
    name = container_or_none or f"{_need('project')}-{service}-1"
    r = _run([_C["docker"], "port", name, f"{cport}/tcp"], check=False, timeout=30)
    line = (r.stdout or "").strip().splitlines()[:1]
    return line[0].rsplit(":", 1)[1] if r.returncode == 0 and line else None


def gw_url(refresh: bool = False, human: bool = False) -> str:
    """게이트웨이 HTTPS 주소. 기본은 https://localhost:<배정 포트>(기기·기계 토큰 호출). 사람 계정(OIDC 로그인)은 human=True: 밖에서 보이는 주소 GATEWAY_PUBLIC_URL(첫 GATEWAY_HOSTS 이름 + 밖에 보이는 포트)을 쓴다.
    왜: 로그인 쿠키와 Keycloak 의 허용 리다이렉트는 그 이름에만 묶인다(U82, ADR 0057). 포트는 캐시하고 refresh=True 로 다시 묻는다."""
    if refresh or "_gw_port" not in _C:
        p = _docker_port(None, "gateway", "8443")
        if not p:
            raise RuntimeError("게이트웨이 TLS 호스트 포트를 읽지 못했다(docker port)")
        _C["_gw_port"] = p
    if human:
        pub = os.environ.get("GATEWAY_PUBLIC_URL", "")
        if not pub:
            raise RuntimeError("GATEWAY_PUBLIC_URL 이 없다: scripts/lib.sh 를 source 한 셸(e2e.sh·demo.sh)에서 돌려야 한다")
        return pub
    return f"https://localhost:{_C['_gw_port']}"


def _test_password(account: str) -> str:
    # 왜 파일: 시험 사용자의 암호는 비밀 폴더의 파일(tokens/idp-test-<id>-password, gen-secrets --test-fixtures)에서만 읽는다(D84). 값은 로그인 요청 본문에만 쓴다
    return (_need("secrets") / "tokens" / f"idp-test-{account}-password").read_text().strip()


def _cookies_of(headers) -> dict:
    out = {}
    for h in headers.get_all("Set-Cookie") or []:
        nv = h.split(";", 1)[0]
        if "=" in nv:
            k, v = nv.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def oidc_login(base: str, username: str, password: str, *, ca: str, rd: str = "/") -> dict:
    """브라우저가 하는 OIDC 로그인(인가 코드 흐름)을 따라 한다: GET /oauth2/start -> Keycloak 로그인 화면 -> 양식 POST -> /oauth2/callback -> 세션 쿠키.
    반환: 쿠키 dict(oauth2-proxy 세션). 실패(잘못된 암호, 가입 승인 대기 아님의 오류 등)는 RuntimeError(암호는 싣지 않는다)."""
    import html as _html
    import re as _re
    ctx = ssl.create_default_context(cafile=str(ca))
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    jar: dict = {}

    def req(method, url, data=None, headers=None):
        h = dict(headers or {})
        if jar:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        r = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with op.open(r, timeout=30) as resp:
                jar.update(_cookies_of(resp.headers)); return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            jar.update(_cookies_of(e.headers)); return e.code, dict(e.headers), e.read().decode("utf-8", "replace")

    url = base + "/oauth2/start?rd=" + urllib.parse.quote(rd, safe="")
    page = None
    for _ in range(12):   # 리다이렉트를 최대 12번 따라간다(시작 -> Keycloak -> 콜백 -> rd)
        st, hd, body = req("GET", url)
        loc = hd.get("Location") or hd.get("location")
        if st in (301, 302, 303, 307, 308) and loc:
            url = urllib.parse.urljoin(url, loc)
            if "/oauth2/callback" in url and "_openit_session" in jar:
                break
            continue
        page = body
        break
    if page is None:
        # 콜백까지 따라갔거나 세션이 이미 있다
        if "_openit_session" in jar:
            return jar
        raise RuntimeError("로그인 화면에 닿지 못했다")
    m = _re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page) or _re.search(r'<form[^>]*action="([^"]+)"[^>]*id="kc-form-login"', page)
    if not m:
        raise RuntimeError("Keycloak 로그인 양식을 찾지 못했다")
    action = _html.unescape(m.group(1))
    form = urllib.parse.urlencode({"username": username, "password": password, "credentialId": ""}).encode()
    st, hd, body = req("POST", urllib.parse.urljoin(url, action), data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
    for _ in range(12):
        loc = hd.get("Location") or hd.get("location")
        if st in (301, 302, 303, 307, 308) and loc:
            nxt = urllib.parse.urljoin(url, loc)
            st, hd, body = req("GET", nxt)
            url = nxt
            continue
        break
    if "_openit_session" not in jar:
        raise RuntimeError(f"로그인 실패(사용자 {username}): 마지막 응답 {st}")
    return jar


def session_cookie(account: str) -> str:
    """시험 사용자 account 의 oauth2-proxy 세션 쿠키 머리글 값. 사용자마다 한 번 로그인하고 캐시한다(만료·거부되면 다시: forget_session)."""
    cache = _C.setdefault("_sessions", {})
    if account not in cache:
        jar = oidc_login(gw_url(human=True), account, _test_password(account), ca=str(_need("gw_ca")))
        cache[account] = "; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("_openit_session"))
    return cache[account]


def forget_session(account: str) -> None:
    _C.setdefault("_sessions", {}).pop(account, None)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # 왜: 게이트웨이의 308/302 를 그대로 단언하려고 따라가지 않는다
        return None


def _opener() -> urllib.request.OpenerDirector:
    ca = _need("gw_ca")
    # 왜 CA 명시: 시스템 신뢰 저장소가 아니라 게이트웨이 내부 CA 만 신뢰한다(자체 서명 인증서가 우연히 통과하는 것을 막는다)
    ctx = ssl.create_default_context(cafile=str(ca))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect, urllib.request.HTTPSHandler(context=ctx))


def gw_request(method: str, path: str, *, account: Optional[str] = None, token: Optional[str] = None, json: Any = None,
               data: Optional[bytes] = None, headers: Optional[dict] = None, timeout: float = 10.0) -> tuple[int, dict, bytes]:
    """게이트웨이로 한 요청. (상태, 소문자 키 헤더 dict, 본문 바이트). 4xx/5xx 도 예외 없이 돌려준다. 연결 실패는 OSError(URLError)."""
    body = _json.dumps(json, ensure_ascii=False).encode() if json is not None else data
    h = dict(headers or {})
    if json is not None:
        h.setdefault("Content-Type", "application/json")
    elif data is not None:
        h.setdefault("Content-Type", "application/octet-stream")
    if account and token:
        raise ValueError("account 와 token 은 함께 쓸 수 없다(Authorization 하나)")
    if account:
        h["Cookie"] = session_cookie(account)   # 사람 계정은 OIDC 로그인 세션 쿠키(U82). 기기·기계 토큰은 Authorization: Bearer
    elif token:
        h["Authorization"] = "Bearer " + token
    op = _opener()
    last: Optional[BaseException] = None
    for attempt in (0, 1):
        req = urllib.request.Request(gw_url(refresh=attempt == 1, human=bool(account)) + path, data=body, method=method, headers=h)
        try:
            with op.open(req, timeout=timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
        except urllib.error.URLError as e:
            last = e   # 왜 한 번 더: 게이트웨이를 다시 띄운 단계 뒤 포트가 바뀌었을 수 있다. 같은 오류면 그대로 올린다
    raise last  # type: ignore[misc]


def gw_client(cls, *, account: Optional[str] = None, token: Optional[str] = None, user: Optional[str] = None):
    """boundary_contracts 클라이언트 cls 를 게이트웨이 주소로 만든다. HTTPS 검증은 init 이 둔 SSL_CERT_FILE(게이트웨이 CA)로 한다."""
    if account and token:
        raise ValueError("account 와 token 은 함께 쓸 수 없다")
    c = cls(gw_url(human=bool(account)), token, **({"user": user} if user is not None else {}))
    if account:
        # 왜 _headers: 클라이언트는 Bearer 토큰만 받는다. 사람 계정은 게이트웨이의 OIDC 세션 쿠키라 하위 클래스가 더하는 고정 헤더(_headers, 클라이언트가 문서화한 확장점)에
        # 싣는다. 토큰이 없으면 클라이언트가 Authorization 을 덮어쓰지 않는다. 클라이언트 코드를 복사하거나 고치지 않는다.
        c._headers["Cookie"] = session_cookie(account)
    return c


# ---- (b) 제품 네트워크 안에서 ----
def exec_in(service: str, argv: list[str], *, input: Optional[str] = None, timeout: float = 60, check: bool = True) -> subprocess.CompletedProcess:
    """`docker compose -p P exec -T <service> argv`. 제품 컨테이너 안에서 명령을 실행한다."""
    return _run(_dc("exec", "-T", service, *argv), input=input, timeout=timeout, check=check)


def exec_py(service: str, code: str, *, timeout: float = 60) -> str:
    """그 컨테이너의 python 으로 code 를 실행한다(stdin 으로 넘긴다: 인자·프로세스 목록에 남기지 않는다). 반환은 stdout. 호출자가 JSON 으로 주고받는다."""
    return exec_in(service, ["python", "-"], input=code, timeout=timeout).stdout


def run_job(job: str, args=(), *, env: Optional[dict] = None, timeout: float = 300) -> subprocess.CompletedProcess:
    """`docker compose -p P --profile jobs run --rm --no-deps <job> args`. 제품의 잡을 제품 네트워크 안에서 한 번 실행한다(scripts/run-job.sh 와 같은 호출)."""
    envs = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
    return _run(_dc("--profile", "jobs", "run", "--rm", "--no-deps", *envs, job, *args), timeout=timeout, check=False)


_READYZ = ("import json,sys,urllib.request,urllib.error\n"
           "try:\n r=urllib.request.urlopen('https://'+SERVICE+'/readyz',timeout=5); c,b=r.status,r.read()\n"
           "except urllib.error.HTTPError as e: c,b=e.code,e.read()\n"
           "try: d=json.loads(b)\nexcept Exception: d={'raw':b.decode(errors='replace')[:200]}\n"
           "print(json.dumps([c,d]))\n")


def readyz(service: str) -> tuple[int, dict]:
    """컨테이너 안에서 중계(TLS 종단)를 거쳐 https://<서비스 이름>/readyz (R4.3·R5.1: 앱 포트 직접 호출이 아니다). 왜 python: 서비스 이미지(파이썬)에는 wget 이 없고 python 은 있다(e2e.sh 의 reach 도 같은 방식)."""
    c, d = json.loads(exec_py(service, "SERVICE = %r\n" % service + _READYZ, timeout=30).strip().splitlines()[-1])
    return c, d


def psql(db_service: str, sql: str, *, db: str = "postgres", user: str = "postgres", timeout: float = 60) -> str:
    """postgres 컨테이너 안에서 psql -tA 로 SQL 한 문장을 실행하고 stdout 을 돌려준다. 왜 컨테이너 안: 데이터베이스는 호스트에 게시하지 않는다. 비밀은 쓰지 않는다(소켓 인증)."""
    return exec_in(db_service, ["psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tAc", sql], timeout=timeout).stdout


def logs(service: str, since: Optional[str] = None) -> str:
    """`docker compose -p P logs --no-color --no-log-prefix [--since X] <service>`. 왜: 게이트웨이 접근 로그의 duration 등을 컨테이너 밖 포트 없이 읽는다."""
    extra = ["--since", since] if since else []
    return _run(_dc("logs", "--no-color", "--no-log-prefix", *extra, service), timeout=60).stdout


# ---- (c) 다른 호스트 역할의 추론 서버 ----
def inference_url() -> Optional[str]:
    """별도 프로젝트로 띄운 추론 서버의 호스트 주소 https://host.docker.internal:<포트>. 없으면 None. 왜 docker port: 그 컨테이너가 자기 게시 포트를 Docker 에게서 배정받는다."""
    ip = _C.get("inference_project")
    if not ip:
        return None
    p = _docker_port(f"{ip}-model-serving-net-1", "model-serving", "443")
    return f"https://localhost:{p}" if p else None   # 인증서 SAN 에 localhost 가 있다(e2e.sh 가 토큰·인증서에 함께 넣는다)   # 서비스 TLS 사이드카(ADR 0060)가 받는 https. 인증서 이름이 host.docker.internal 이라 그 이름으로 부른다. 검증 루트는 호출 프로세스의 SSL_CERT_FILE(e2e.sh 가 step-ca 루트를 준다)
