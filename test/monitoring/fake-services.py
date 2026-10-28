"""감시 스택 시험용 가짜 서비스: /healthz 200, /readyz 는 /state/mode 에 따라 release-gate 모양의 JSON(judging_loop)을 낸다.
mode: ok(정상) | fail3(연속 실패 3회, 503) | down(503, judging_loop 없음). 시험 전용이며 운영 구성에 들어가지 않는다."""
import http.server, json, time
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/healthz": return self._send(200, {"status": "ok"})
        if self.path == "/readyz":
            mode = open("/state/mode").read().strip() if __import__("os").path.exists("/state/mode") else "ok"
            if mode == "down": return self._send(503, {"status": "down"})
            f = 3 if mode == "fail3" else 0
            return self._send(503 if f else 200, {"status": "x", "judging": "enabled", "judging_loop": {"last_run_at": int(time.time()) - 5, "consecutive_failures": f, "last_error": None, "upstream_auth_failed": False}})
        self._send(404, {})
    def _send(self, code, body):
        b = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
http.server.ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
