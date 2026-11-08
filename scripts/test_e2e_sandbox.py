#!/usr/bin/env python3
"""e2e_sandbox 의 명령 조립 단위 시험. 가짜 실행기로 인자만 본다(Docker·네트워크·실제 시간을 쓰지 않는다)."""
import os, pathlib, subprocess, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import e2e_sandbox as S


class Fake:
    def __init__(self, stdout="", rc=0): self.calls, self.stdout, self.rc = [], stdout, rc
    by_verb = {}
    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        out = next((v for k, v in self.by_verb.items() if k in cmd[:3]), self.stdout)
        return subprocess.CompletedProcess(cmd, self.rc, out, "")


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        (pathlib.Path(self.tmp.name) / "tokens").mkdir()
        (pathlib.Path(self.tmp.name) / "tokens" / "idp-test-op-e2e-password").write_text("pw-for-test\n")
        self.f = Fake()
        S.init(project="P1", secrets=self.tmp.name, gw_ca="", docker="docker", inference_project="P1-inf", root="/r", run=self.f)

    def last(self): return self.f.calls[-1][0]

    def test_init_rejects_unknown_and_missing(self):
        with self.assertRaises(TypeError): S.init(project="p", secrets="s", bogus=1)
        with self.assertRaises(TypeError): S.init(project="p")

    def _client(self, **kw):
        self.f.by_verb = {"inspect": "bridge|[\"PATH=/x\",\"GATE_WRITE_TOKENS_FILE=/run/secrets/gate-write-tokens\",\"SOME_TOKEN=should-not-pass\",\"SSL_CERT_FILE=/etc/openit/pki/root_ca.crt\"]|P1_a P1_b ", "create": "cid123\n", "start": "{\"ok\": 1}"}
        S.init(project="P1", secrets=self.tmp.name, gw_ca="/ca/trust.crt", docker="docker", inference_project="P1-inf", root="/r", run=self.f, tool_image="deploy-tool:t", secrets_gid="1234", **kw)

    def test_exec_py_runs_in_a_client_on_the_same_networks(self):
        self._client()
        out = S.exec_py("release-gate", "print(@SELF@)".replace("@SELF@", S.SELF))
        self.assertEqual(out, '{"ok": 1}')
        verbs = [c[0][1] for c in self.f.calls[-6:]]
        self.assertEqual(verbs, ["inspect", "create", "network", "start", "rm"])
        insp = next(c for c in self.f.calls if c[0][1] == "inspect")[0]; self.assertEqual(insp[2], "P1-release-gate-1")   # 바깥에서 본다
        create = next(c for c in self.f.calls if c[0][1] == "create")[0]
        self.assertIn("--read-only", create); self.assertIn("P1_a", create)
        i = create.index("--tmpfs"); self.assertEqual(create[i + 1], "/tmp:rw,noexec,nosuid,size=256m,uid=10001,gid=10001,mode=0700")   # 읽기 전용 루트에서 tempfile.mkdtemp 가 쓸 곳(uid 10001 소유)
        self.assertNotIn("exec", [c[0][1] for c in self.f.calls])   # 영역 컨테이너에 docker exec 로 들어가지 않는다(주석 안에 있어 실행되지 않던 단언, Codex 검토)
        self.assertIn("GATE_WRITE_TOKENS_FILE=/run/secrets/gate-write-tokens", create)   # *_FILE(파일 경로) 만 옮긴다
        self.assertFalse(any("should-not-pass" in x for x in create), "*_FILE 이 아닌 환경은 옮기지 않는다")
        self.assertIn("SSL_CERT_FILE=/ca.crt", create); self.assertIn("/ca/trust.crt:/ca.crt:ro", create)   # 인증서 검증을 끄지 않는다
        self.assertEqual([x for x in create if x.startswith("SSL_CERT_FILE=")], ["SSL_CERT_FILE=/ca.crt"], "서비스의 SSL_CERT_FILE(그 컨테이너의 경로)이 신뢰 루트를 덮어쓰면 안 된다(2026-11-08 단계 1)")
        self.assertIn("1234", create)
        tok = os.path.join(self.tmp.name, "tokens", "idp-test-op-e2e-password")
        self.assertIn(f"{tok}:/run/secrets/idp-test-op-e2e-password:ro", create)   # 파일마다 붙인다: 폴더(700)째 붙이면 uid 10001 이 들어가지 못한다(2026-11-08 단계 1·5a)
        self.assertFalse(any(x.endswith("/tokens:/run/secrets:ro") for x in create))
        conn = next(c for c in self.f.calls if c[0][1] == "network")[0]; self.assertEqual(conn[-2:], ["P1_b", "cid123"])
        start = next(c for c in self.f.calls if c[0][1] == "start"); self.assertEqual(start[1]["input"], "print(https://release-gate)")   # SELF 가 영역 게이트웨이 주소가 된다

    def test_exec_py_removes_the_client_even_when_it_fails(self):
        self._client()
        orig = self.f.__class__.__call__
        calls = self.f.calls
        class Boom(Exception): pass
        def run(cmd, **kw):
            calls.append((cmd, kw))
            if cmd[1] == "start": return subprocess.CompletedProcess(cmd, 3, "", "boom")
            return subprocess.CompletedProcess(cmd, 0, {"inspect": "bridge|[]|n ", "create": "c9"}.get(cmd[1], ""), "")
        S._C["run"] = run
        with self.assertRaises(RuntimeError): S.exec_py("survey-service", "x")
        self.assertEqual(calls[-1][0][1:3], ["rm", "-f"])

    def test_model_serving_is_the_inference_projects_container(self):
        self._client(); S.exec_py("model-serving", "x")
        self.assertEqual(next(c for c in self.f.calls if c[0][1] == "inspect")[0][2], "P1-inf-model-serving-1")

    def test_run_job(self):
        S.run_job("job-x", ["a", "b"], env={"K": "V"})
        self.assertEqual(self.last()[-11:], ["P1", "--profile", "jobs", "run", "--rm", "--no-deps", "-e", "K=V", "job-x", "a", "b"])

    def test_logs(self):
        S.logs("gateway", since="30s")
        self.assertEqual(self.last()[-7:], ["P1", "logs", "--no-color", "--no-log-prefix", "--since", "30s", "gateway"])

    def test_readyz_parses(self):
        self._client(); self.f.by_verb["start"] = '[503, {"ready": false}]\n'
        self.assertEqual(S.readyz("survey-service"), (503, {"ready": False}))

    def test_gw_url_and_cache(self):
        self.f.stdout = "0.0.0.0:49153\n[::]:49153\n"
        self.assertEqual(S.gw_url(), "https://localhost:49153"); n = len(self.f.calls)
        S.gw_url(); self.assertEqual(len(self.f.calls), n)   # 캐시
        self.assertEqual(self.f.calls[0][0], ["docker", "port", "P1-gateway-1", "8443/tcp"])

    def test_inference_url(self):
        self.f.stdout = "127.0.0.1:40001\n"
        self.assertEqual(S.inference_url(), "https://host.docker.internal:40001")   # 인증서 SAN 의 이름(localhost 아님)
        self.assertEqual(self.last(), ["docker", "port", "P1-inf-model-serving-net-1", "443/tcp"])
        self.f.rc = 1; self.assertIsNone(S.inference_url())

    def test_crash_signals_the_pid_from_the_host_pid_namespace(self):
        self._client(); self.f.by_verb = {"inspect": "4242\n"}
        S.crash("P1-survey-service-1")
        insp, run = self.f.calls[-2][0], self.f.calls[-1][0]
        self.assertEqual(insp, ["docker", "inspect", "-f", "{{.State.Pid}}", "P1-survey-service-1"])
        self.assertEqual(run[:2], ["docker", "run"]); self.assertNotIn("kill", run[:3])   # docker kill 은 사람이 멈춘 것으로 기록돼 restart 정책이 돌지 않는다
        for a, b in (("--pid", "host"), ("--cap-add", "KILL"), ("--cap-drop", "ALL"), ("--network", "none")): self.assertEqual(run[run.index(a) + 1], b)
        self.assertEqual(run[-1], "import os; os.kill(4242, 9)")
        self.f.by_verb = {"inspect": "0\n"}
        with self.assertRaises(RuntimeError): S.crash("P1-survey-service-1")

    def test_inference_open_verifies_the_san_name_and_connects_to_the_published_address(self):
        # 실제 TLS: SAN 이 host.docker.internal 하나인 인증서로 127.0.0.1 에 서버를 띄운다. 이름 검증을 끄지 않고, 다른 이름(localhost)은 실패해야 한다
        import http.server, ssl, threading, urllib.request
        d = pathlib.Path(self.tmp.name)
        r = subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "1", "-subj", "/CN=host.docker.internal",
                            "-addext", "subjectAltName=DNS:host.docker.internal", "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")], capture_output=True)
        if r.returncode != 0: self.skipTest("openssl 로 시험 인증서를 만들지 못했다")
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(self.headers.get("Host", "").encode())
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(str(d / "c.pem"), str(d / "k.pem"))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        S.init(project="P1", secrets=self.tmp.name, gw_ca=str(d / "c.pem"), docker="docker", inference_project="P1-inf", root="/r", run=self.f)
        self.f.stdout = f"0.0.0.0:{port}\n"
        url = S.inference_url(); self.assertEqual(url, f"https://host.docker.internal:{port}")
        with S.inference_open(urllib.request.Request(url + "/x"), timeout=10) as resp:
            self.assertEqual(resp.status, 200); self.assertEqual(resp.read().decode(), f"host.docker.internal:{port}")
        with self.assertRaises(Exception) as e:   # 같은 서버를 localhost 로 부르면 이름 검증이 실패한다(검증이 켜져 있다)
            S.inference_open(urllib.request.Request(f"https://localhost:{port}/x"), timeout=10)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(e.exception))

    def test_gw_client_account_header_and_user(self):
        # 사람 계정은 OIDC 로그인 세션 쿠키(U82): 로그인은 session_cookie 가 하므로 여기서는 대신한다. 기본 주소는 밖에서 보이는 주소(GATEWAY_PUBLIC_URL)다
        self.f.stdout = "0.0.0.0:49153\n"
        class C:
            def __init__(self, base, token, timeout=10.0, *, user=None): self.base, self.token, self.user, self._headers = base, token, user, {}
        import os
        old = os.environ.get("GATEWAY_PUBLIC_URL"); os.environ["GATEWAY_PUBLIC_URL"] = "https://localhost:49153"
        orig = S.session_cookie; S.session_cookie = lambda a: f"_openit_session={a}-cookie"
        try:
            c = S.gw_client(C, account="op-e2e", user="u1")
            self.assertEqual(c.base, "https://localhost:49153"); self.assertIsNone(c.token); self.assertEqual(c.user, "u1")
            self.assertEqual(c._headers["Cookie"], "_openit_session=op-e2e-cookie"); self.assertNotIn("Authorization", c._headers)
        finally:
            S.session_cookie = orig
            if old is None: os.environ.pop("GATEWAY_PUBLIC_URL", None)
            else: os.environ["GATEWAY_PUBLIC_URL"] = old
        c2 = S.gw_client(C, token="tok"); self.assertEqual(c2.token, "tok"); self.assertNotIn("Authorization", c2._headers); self.assertEqual(c2.base, "https://localhost:49153")
        with self.assertRaises(ValueError): S.gw_client(C, account="a", token="t")

    def test_test_password_comes_from_file(self):
        self.assertEqual(S._test_password("op-e2e"), "pw-for-test")

    def test_cookies_of_reads_set_cookie(self):
        import email.message
        m = email.message.Message(); m["Set-Cookie"] = "_openit_session=abc; Path=/; Secure; HttpOnly"; m["Set-Cookie"] = "_openit_session_1=def; Path=/"
        self.assertEqual(S._cookies_of(m), {"_openit_session": "abc", "_openit_session_1": "def"})

    def test_human_gw_url_needs_public_url(self):
        import os
        old = os.environ.pop("GATEWAY_PUBLIC_URL", None); self.f.stdout = "0.0.0.0:49153\n"
        try:
            with self.assertRaises(RuntimeError): S.gw_url(human=True)
        finally:
            if old is not None: os.environ["GATEWAY_PUBLIC_URL"] = old

if __name__ == "__main__":
    unittest.main()
