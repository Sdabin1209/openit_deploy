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
        (pathlib.Path(self.tmp.name) / "tokens" / "account-op-e2e-password").write_text("pw-for-test\n")
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
        self.assertEqual(self.last(), ["docker", "port", "P1-inf-model-serving-1", "8080/tcp"])
        self.f.rc = 1; self.assertIsNone(S.inference_url())

    def test_gw_client_account_header_and_user(self):
        self.f.stdout = "0.0.0.0:49153\n"
        class C:
            def __init__(self, base, token, timeout=10.0, *, user=None): self.base, self.token, self.user, self._headers = base, token, user, {}
        c = S.gw_client(C, account="op-e2e", user="u1")
        self.assertEqual(c.base, "https://127.0.0.1:49153"); self.assertIsNone(c.token); self.assertEqual(c.user, "u1")
        self.assertTrue(c._headers["Authorization"].startswith("Basic "))
        c2 = S.gw_client(C, token="tok"); self.assertEqual(c2.token, "tok"); self.assertNotIn("Authorization", c2._headers)
        with self.assertRaises(ValueError): S.gw_client(C, account="a", token="t")


if __name__ == "__main__":
    unittest.main()
