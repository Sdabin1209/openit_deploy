#!/usr/bin/env python3
"""e2e_sandbox 의 명령 조립 단위 시험. 가짜 실행기로 인자만 본다(Docker·네트워크·실제 시간을 쓰지 않는다)."""
import pathlib, subprocess, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import e2e_sandbox as S


class Fake:
    def __init__(self, stdout="", rc=0): self.calls, self.stdout, self.rc = [], stdout, rc
    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, "")


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

    def test_exec_in(self):
        S.exec_in("release-gate", ["ls", "/"], input="x", timeout=5)
        c = self.last(); self.assertEqual(c[-6:], ["P1", "exec", "-T", "release-gate", "ls", "/"]); self.assertEqual(self.f.calls[-1][1]["input"], "x")

    def test_exec_in_check_raises(self):
        self.f.rc = 3
        with self.assertRaises(RuntimeError): S.exec_in("a", ["b"])
        self.assertEqual(S.exec_in("a", ["b"], check=False).returncode, 3)

    def test_exec_py_uses_stdin(self):
        self.f.stdout = "{}"
        self.assertEqual(S.exec_py("survey-service", "print(1)"), "{}")
        self.assertEqual(self.last()[-3:], ["survey-service", "python", "-"]); self.assertEqual(self.f.calls[-1][1]["input"], "print(1)")

    def test_run_job(self):
        S.run_job("job-x", ["a", "b"], env={"K": "V"})
        self.assertEqual(self.last()[-11:], ["P1", "--profile", "jobs", "run", "--rm", "--no-deps", "-e", "K=V", "job-x", "a", "b"])

    def test_logs(self):
        S.logs("gateway", since="30s")
        self.assertEqual(self.last()[-7:], ["P1", "logs", "--no-color", "--no-log-prefix", "--since", "30s", "gateway"])

    def test_psql(self):
        S.psql("postgres", "select 1", db="qa")
        self.assertEqual(self.last()[-10:], ["postgres", "psql", "-U", "postgres", "-d", "qa", "-v", "ON_ERROR_STOP=1", "-tAc", "select 1"])

    def test_readyz_parses(self):
        self.f.stdout = '[503, {"ready": false}]\n'
        self.assertEqual(S.readyz("survey-service"), (503, {"ready": False}))

    def test_gw_url_and_cache(self):
        self.f.stdout = "0.0.0.0:49153\n[::]:49153\n"
        self.assertEqual(S.gw_url(), "https://127.0.0.1:49153"); n = len(self.f.calls)
        S.gw_url(); self.assertEqual(len(self.f.calls), n)   # 캐시
        self.assertEqual(self.f.calls[0][0], ["docker", "port", "P1-gateway-1", "8443/tcp"])

    def test_inference_url(self):
        self.f.stdout = "127.0.0.1:40001\n"
        self.assertEqual(S.inference_url(), "http://127.0.0.1:40001")
        self.assertEqual(self.last(), ["docker", "port", "P1-inf-model-serving-net-1", "443/tcp"])
        self.f.rc = 1; self.assertIsNone(S.inference_url())

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
        c2 = S.gw_client(C, token="tok"); self.assertEqual(c2.token, "tok"); self.assertNotIn("Authorization", c2._headers); self.assertEqual(c2.base, "https://127.0.0.1:49153")
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
