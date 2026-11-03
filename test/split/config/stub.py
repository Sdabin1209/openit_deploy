# 분리 배치 시험용 대역 서비스(표준 라이브러리만). GET /healthz -> 200. GET /call?env=<변수 이름> -> 그 환경 변수의 주소 + /healthz 를 불러 상태 코드를 돌려준다.
# 왜 대역인가: 실제 이미지는 레지스트리의 digest 로만 받는다. 이 시험이 보는 것은 배치(주소 계산, 게시 포트, 네트워크 분리)이지 영역의 동작이 아니다.
import http.server, os, urllib.parse, urllib.request, ssl

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/healthz", "/readyz"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if u.path == "/call":
            var = urllib.parse.parse_qs(u.query)["env"][0]
            url = os.environ[var].rstrip("/") + "/healthz"
            ctx = ssl.create_default_context(cafile=os.environ["STUB_CA"]) if os.environ.get("STUB_CA") else None
            try:
                code = urllib.request.urlopen(url, timeout=3, context=ctx).status
            except Exception as e:
                code = 599; url += " " + repr(e)[:120]
            self.send_response(200); self.end_headers(); self.wfile.write(("%s %d" % (url, code)).encode()); return
        self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

import threading
# 8080(서비스)과 5432(postgres 대역): 서비스마다 컨테이너 포트가 다르다(scripts/placement.py CONTAINER_PORT)
for port in (5432, 8080):
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    (threading.Thread(target=srv.serve_forever, daemon=True).start() if port == 5432 else None)
srv.serve_forever()
