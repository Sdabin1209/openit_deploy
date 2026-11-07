#!/usr/bin/env python3
"""check_unauth.py 단독 시험: 가짜 입구(http.server)로 기대 행의 생성과 판정을 본다. 계약 규칙(RUNTIME R3.13·R3.23, CONVENTIONS 9절)대로 답하는 가짜는 통과하고, 규칙을 어기는 가짜(변이)는 실패한다.
Docker 불필요. 사용: python3 scripts/test_check_unauth.py"""
import http.server, json, pathlib, sys, tempfile, threading, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_unauth as C  # noqa: E402

EXPO = {"service": "t", "routes": [
    {"paths": ["/v1/sessions/*/turns"], "methods": ["POST"], "auth": {"kind": "device"}},
    {"paths": ["/v1/staff/alerts"], "methods": ["GET"], "auth": {"kind": "account", "roles": ["staff"]}},
    {"paths": ["/staff/*"], "methods": ["GET"], "auth": {"kind": "authenticated"}},
    {"paths": ["/healthz"], "auth": {"kind": "none"}}, {"paths": ["/v1/internal"], "auth": {"kind": "denied"}}]}

def serve(mutation=None):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(s, *a): pass
        def _send(s, st, www=None, loc=None, code=None):
            s.send_response(st)
            if www: s.send_header("WWW-Authenticate", www)
            if loc: s.send_header("Location", loc)
            s.end_headers(); s.wfile.write(json.dumps({"code": code}).encode() if code else b"")
        def handle_any(s):
            p = s.path; html = "text/html" in s.headers.get("Accept", "")
            if p.startswith("/v1/sessions/") and s.command == "POST":
                return s._send(200 if mutation == "open-device" else 403 if mutation != "device-401" else 401, code="PERMISSION_DENIED")
            if p == "/v1/staff/alerts":
                return s._send(401, "Bearer" if mutation == "no-realm" else 'Bearer realm="openit"', code="PERMISSION_DENIED")
            if p.startswith("/staff/"):
                if html and mutation != "no-redirect": return s._send(302, loc="/oauth2/start")
                return s._send(401, 'Bearer realm="openit"')
            return s._send(404, code="NOT_FOUND")
        do_GET = do_POST = handle_any
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

class T(unittest.TestCase):
    def run_against(self, mutation=None, expo=EXPO):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "t.json").write_text(json.dumps(expo)); srv = serve(mutation)
            try: return C.main([f"http://127.0.0.1:{srv.server_port}", "--exposures", d])
            finally: srv.shutdown()
    def test_rows_come_from_the_declaration(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "t.json").write_text(json.dumps(EXPO)); descs = [r[0] for r in C.rows(d)]
        self.assertEqual(len(descs), 5, descs)   # device 1 + API 1 + 화면 2 + 선언 없는 경로 1 (none·denied 는 행이 없다)
        self.assertFalse(any("healthz" in x or "internal" in x for x in descs))
    def test_contract_following_server_passes(self): self.assertEqual(self.run_against(), 0)
    def test_mutation_open_device_route_fails(self): self.assertEqual(self.run_against("open-device"), 1)
    def test_mutation_device_route_answers_401_fails(self): self.assertEqual(self.run_against("device-401"), 1)   # F절: 기기 경로의 인증서 없음은 401 이 아니라 403
    def test_mutation_missing_realm_fails(self): self.assertEqual(self.run_against("no-realm"), 1)
    def test_mutation_no_redirect_for_html_fails(self): self.assertEqual(self.run_against("no-redirect"), 1)
    def test_empty_declarations_fail(self): self.assertEqual(self.run_against(expo={"service": "t", "routes": []}), 1)
    def test_https_needs_cacert(self):
        with tempfile.TemporaryDirectory() as d: self.assertEqual(C.main(["https://x:1", "--exposures", d]), 2)

if __name__ == "__main__": unittest.main()
