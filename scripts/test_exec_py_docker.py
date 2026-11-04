#!/usr/bin/env python3
"""e2e_sandbox.exec_py 실제 Docker 시험: 서비스(가짜) 컨테이너와 같은 망에서 클라이언트가 돌고, 비밀 폴더의 토큰을 /run/secrets 로 읽고, *_FILE 환경만 옮기고, 클라이언트는 끝나면 지워진다.
도구 이미지 자리에 UTIL(python) 이미지를 쓴다(link 설치 여부는 build-tool-image.sh 의 몫). Docker 가 없으면 SKIP(77). 사용: python3 scripts/test_exec_py_docker.py"""
import json, os, pathlib, subprocess, sys, tempfile, time, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import e2e_sandbox as S  # noqa: E402

D = "docker"
UTIL = next((l.split("=", 1)[1].strip() for l in (ROOT / "locks/images.lock").read_text().splitlines() if l.startswith("UTIL_IMAGE=")), "")
def dk(*a, **kw): return subprocess.run([D, *a], capture_output=True, text=True, **kw)
if subprocess.run([D, "version"], capture_output=True).returncode != 0 or not UTIL: print("SKIP: Docker 또는 UTIL 이미지가 없다"); sys.exit(77)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.id = str(os.getpid()); cls.net = f"xpy-n-{cls.id}"; cls.other = f"xpy-o-{cls.id}"; cls.proj = f"xpy{cls.id}"
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build" / "logs"); t = pathlib.Path(cls.tmp.name)
        (t / "tokens").mkdir(); (t / "tokens" / "gate-read").write_text("tok-abc\n"); os.chmod(t / "tokens", 0o755); os.chmod(t / "tokens" / "gate-read", 0o644)
        (t / "ca.crt").write_text("")
        www = t / "www"; www.mkdir(); (www / "healthz").write_text("ok"); os.chmod(www, 0o755); os.chmod(www / "healthz", 0o644)
        dk("network", "create", cls.net); dk("network", "create", cls.other)
        cls.svc = f"{cls.proj}-svc-1"
        dk("run", "-d", "--name", cls.svc, "--network", cls.net, "--network-alias", "svc", "-e", "GATE_READ_FILE=/run/secrets/gate-read", "-e", "NOT_FILE_VALUE=secret-should-not-pass", "-v", f"{www}:/www:ro", UTIL, "python", "-m", "http.server", "80", "-d", "/www")
        cls.far = f"{cls.proj}-far-1"; dk("run", "-d", "--name", cls.far, "--network", cls.other, UTIL, "sleep", "120")
        S.init(project=cls.proj, secrets=str(t), gw_ca=str(t / "ca.crt"), docker=D, inference_project=cls.proj + "-inf", root=str(ROOT), tool_image=UTIL, secrets_gid=str(os.getgid()))
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        dk("rm", "-f", cls.svc, cls.far); dk("network", "rm", cls.net, cls.other); cls.tmp.cleanup()

    def test_same_network_token_and_file_env_only(self):
        out = S.exec_py("svc", "import os,urllib.request\nprint(urllib.request.urlopen('http://svc/healthz',timeout=5).read().decode())\n"
                        "print(open(os.environ['GATE_READ_FILE']).read().strip())\nprint('NOT_FILE_VALUE' in os.environ)\nprint('@SELF@'.replace('@SELF@', %r))\n" % "x")
        self.assertEqual(out.split(), ["ok", "tok-abc", "False", "x"])

    def test_self_is_the_service_gateway_name(self):
        self.assertEqual(S.exec_py("svc", "print('" + S.SELF + "')").strip(), "https://svc")

    def test_other_network_service_is_unreachable(self):
        out = S.exec_py("far", "import urllib.request\ntry: urllib.request.urlopen('http://svc/healthz',timeout=3); print('reach')\nexcept Exception: print('unreachable')\n")
        self.assertEqual(out.strip(), "unreachable")

    def test_client_is_removed(self):
        S.exec_py("svc", "print(1)")
        left = dk("ps", "-aq", "--filter", "ancestor=" + UTIL, "--filter", "status=exited").stdout.split()
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
