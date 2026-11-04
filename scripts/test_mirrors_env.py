#!/usr/bin/env python3
"""정적·단독 시험(S14): 영역 시험·빌드를 돌리는 deploy 도구(check-all, verify-area, build-images)가 영역 실행 환경에 로컬 미러 git 설정(GIT_CONFIG_GLOBAL)을 준다.
변이 확인: 도구에서 mirrors.ensure_env 호출을 빼면 실패한다(복사본으로 확인)."""
import os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.wiring import mirrors  # noqa: E402

USERS = ["openit_deploy/wiring/cli_check_all.py", "openit_deploy/wiring/verify_area.py"]


def calls(text):
    return "mirrors.ensure_env()" in text


class T(unittest.TestCase):
    def test_ensure_env_sets_a_file_with_insteadof(self):
        env = {}
        p = mirrors.ensure_env(env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], p)
        self.assertIn("insteadOf", Path(p).read_text(encoding="utf-8"))

    def test_existing_value_is_respected(self):
        env = {"GIT_CONFIG_GLOBAL": "/x/y"}
        self.assertEqual(mirrors.ensure_env(env), "/x/y")

    def test_area_test_runners_call_it(self):
        for u in USERS:
            self.assertTrue(calls((ROOT / u).read_text(encoding="utf-8")), f"{u}: 영역 시험 환경에 로컬 미러 설정을 주지 않는다")
        self.assertIn("GIT_CONFIG_GLOBAL", (ROOT / "scripts/build-images.sh").read_text(encoding="utf-8"))

    def test_mutation_missing_call_is_caught(self):
        for u in USERS:
            self.assertFalse(calls((ROOT / u).read_text(encoding="utf-8").replace("mirrors.ensure_env()", "pass")))


if __name__ == "__main__":
    unittest.main()
