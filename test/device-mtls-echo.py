"""기기 인증서 시험용 가짜 survey-service: 받은 요청 헤더를 JSON 으로 돌려준다(시험 전용)."""
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _r(self):
        n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n) if n else None
        b = json.dumps({k.lower(): v for k, v in self.headers.items()}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = _r
http.server.ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
