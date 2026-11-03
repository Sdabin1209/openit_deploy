"""게이트웨이 시험 전용 가짜 상류(제품 구성에 들어가지 않는다): 받은 요청의 신원 머리글을 JSON 으로 돌려준다. 어떤 경로·메서드든 200. 포트 8080."""
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n: self.rfile.read(n)
        keys = ("X-Openit-User", "X-Openit-Roles", "X-Openit-Device", "X-Openit-Dn", "Authorization", "X-Auth-Request-User", "X-Auth-Request-Preferred-Username", "X-Auth-Request-Groups")
        b = json.dumps({"path": self.path, "headers": {k: self.headers.get_all(k) for k in keys if self.headers.get(k) is not None}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _do
http.server.ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
