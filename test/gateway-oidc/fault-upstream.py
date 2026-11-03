"""게이트웨이 장애 시험 전용 가짜 상류(제품 구성에 들어가지 않는다): 요청 머리글 X-Fault 가 응답을 고른다. 앱이 내는 4xx·5xx BoundaryError 와 413, 임의 머리글, 느린 응답을 만든다."""
import http.server, json, time

BOUNDARY = lambda code, msg: json.dumps({"pipeline_schema_version": "3.4", "code": code, "message": msg, "retryable": False}).encode()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, status, body, ctype="application/json", extra=()):
        self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in extra: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n: self.rfile.read(n)
        elif "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():   # 앱처럼 chunked 본문을 끝까지 읽는다(안 읽으면 게이트웨이의 본문 상한이 동작할 틈이 없다)
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0: self.rfile.readline(); break
                self.rfile.read(size + 2)
        mode = self.headers.get("X-Fault", "ok")
        if mode == "err403": self._send(403, BOUNDARY("PERMISSION_DENIED", "시험 403"), extra=[("X-Test-Custom", "v-403")])
        elif mode == "err500": self._send(500, BOUNDARY("INTERNAL", "시험 500"), extra=[("X-Test-Custom", "v-500")])
        elif mode == "err503": self._send(503, BOUNDARY("UNAVAILABLE", "서비스가 준비되지 않았다"), extra=[("Retry-After", "3"), ("X-Test-Custom", "v-503")])
        elif mode == "err413": self._send(413, BOUNDARY("INVALID_RECORD", "앱이 정한 상한 초과"), extra=[("X-Test-Custom", "v-413")])
        elif mode == "sleep": time.sleep(float(self.headers.get("X-Sleep", "80"))); self._send(200, b'{"late":true}')
        elif mode == "app-headers": self._send(200, b'{"mode":"app-headers"}', extra=[("Cache-Control", "max-age=60"), ("X-Frame-Options", "SAMEORIGIN"), ("Referrer-Policy", "origin"), ("X-Test-Custom", "v-app")])
        elif mode == "empty200": self._send(200, b"", ctype="application/json")
        else: self._send(200, json.dumps({"mode": "ok"}).encode(), extra=[("X-Test-Custom", "v-ok")])
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _do


http.server.ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
