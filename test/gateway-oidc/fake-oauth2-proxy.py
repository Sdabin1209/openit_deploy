"""게이트웨이 시험 전용 가짜 oauth2-proxy(제품 구성에 들어가지 않는다). GET /oauth2/auth 에 쿠키 fakeauth=<계정> 으로 답한다.
계정 -> 그룹 표는 FAKE_ACCOUNTS 파일(`<계정> <역할,역할|->` 줄, # 주석)이다. 쿠키가 없거나 모르는 계정이면 401, 아는 계정이면 202 와 oauth2-proxy 와 같은 응답 머리글
(X-Auth-Request-User=sub, X-Auth-Request-Preferred-Username, X-Auth-Request-Groups: 쉼표 목록, 그룹이 없으면 빈 값)를 낸다. 진짜 oauth2-proxy 와 Keycloak 의 로그인은 scripts/test-idp-smoke.sh 가 본다."""
import http.server, os
T = {}
for line in open(os.environ["FAKE_ACCOUNTS"], encoding="utf-8"):
    s = line.split("#", 1)[0].split()
    if len(s) == 2: T[s[0]] = "" if s[1] == "-" else s[1]
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, headers=()):
        self.send_response(code)
        for k, v in headers: self.send_header(k, v)
        self.send_header("Content-Length", "0"); self.end_headers()
    def do_GET(self):
        if self.path.split("?")[0] != "/oauth2/auth": return self._send(200)   # /oauth2/start 등: 게이트웨이가 전달만 하는지 본다
        c = dict(x.strip().split("=", 1) for x in self.headers.get("Cookie", "").split(";") if "=" in x)
        u = c.get("fakeauth")
        if u not in T: return self._send(401)
        self._send(202, [("X-Auth-Request-User", "sub-" + u), ("X-Auth-Request-Preferred-Username", u), ("X-Auth-Request-Groups", T[u])])   # User 는 sub(내부 식별자), 사용자 ID 는 Preferred-Username
http.server.ThreadingHTTPServer(("0.0.0.0", 4180), H).serve_forever()
