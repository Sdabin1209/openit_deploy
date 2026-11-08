#!/usr/bin/env python3
"""최소 환경 도우미(openit_deploy.wiring.child_env)가 Docker 연결 이름을 전달하고 무관한 이름은 막는지 본다(R9.1). 값은 가짜이고 출력하지 않는다.
사용: python3 -I scripts/test_child_env.py"""
import os, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 왜: python -I 는 scripts 를 sys.path 에 넣지 않는다
from openit_deploy.wiring.child_env import child_env  # noqa: E402

DOCKER_NAMES = ("DOCKER_CONFIG", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SSH_AUTH_SOCK")


class T(unittest.TestCase):
    def test_docker_names_pass(self):
        old = dict(os.environ)
        try:
            for n in DOCKER_NAMES: os.environ[n] = "fake-" + n
            os.environ["UNRELATED_SECRET_TOKEN"] = "fake"
            env = child_env()
            for n in DOCKER_NAMES: self.assertEqual(env.get(n), "fake-" + n, n)
            self.assertNotIn("UNRELATED_SECRET_TOKEN", env)
        finally:
            os.environ.clear(); os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
