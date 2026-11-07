#!/usr/bin/env python3
"""check-all 규칙 8(영역 시험): 건너뛴 시험이 있으면 통과가 아니라 '검증 안 함'이다. 시간이 넘으면 시험 명령의 프로세스 그룹 전체를 끝내 셸 trap 이 정리를 한다.
왜(2026-11-07 교차검증): PostgreSQL 시험 수백 개가 건너뛰어진 채 영역 시험이 통과로 세어졌고, timeout 은 바로 아래 프로세스만 죽여 일회용 DB 가 남을 수 있었다."""
import pathlib, sys, tempfile, unittest
from unittest import mock
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.components import consistency_check as C  # noqa: E402


class T(unittest.TestCase):
    def _run(self, cmd, timeout=None):
        with tempfile.TemporaryDirectory() as d:
            env = mock.Mock()   # 주입 객체(ENV)의 모양: env_status(area, ws), work_root()
            env.env_status = lambda repo, ws: ({"environment": {"test_command": cmd}}, None)
            env.work_root = lambda: pathlib.Path(d)
            with mock.patch.object(C, "ENV", env), mock.patch.object(C, "DEPLOY", ROOT), mock.patch.dict(C.CFG, {"log_dir": d}):
                return self._inner(d, timeout)

    def _inner(self, d, timeout):
        if True:
            (pathlib.Path(d) / "x").mkdir()
            if timeout:
                with mock.patch.object(C, "AREA_TEST_TIMEOUT_SECONDS", timeout):
                    return C.run_area_tests("x", pathlib.Path(d)), pathlib.Path(d)
            return C.run_area_tests("x", pathlib.Path(d)), pathlib.Path(d)

    def test_skipped_tests_are_not_verified(self):
        (st, why), _ = self._run(["sh", "-c", "echo '3 passed, 2 skipped in 0.1s'"])
        self.assertEqual(st, "un"); self.assertIn("건너뜀 2개", why)

    def test_node_test_skips_are_not_verified(self):
        (st, why), _ = self._run(["sh", "-c", "printf 'ℹ tests 9\\nℹ pass 7\\nℹ skipped 2\\n'"])
        self.assertEqual(st, "un"); self.assertIn("건너뜀 2개", why)

    def test_all_passed_without_skips_is_ok(self):
        (st, why), _ = self._run(["sh", "-c", "echo '3 passed in 0.1s'"])
        self.assertEqual(st, "ok"); self.assertIn("건너뜀 0", why)

    def test_timeout_terminates_the_group_and_lets_the_shell_trap_clean_up(self):
        with tempfile.TemporaryDirectory() as m:
            mark = pathlib.Path(m) / "cleaned"
            script = f"trap 'touch {mark}' EXIT; sh -c 'sleep 30' & wait"
            (st, why), _ = self._run(["bash", "-c", script], timeout=1)
            self.assertEqual(st, "fail")
            self.assertTrue(mark.exists(), "SIGTERM 으로 셸의 EXIT trap 이 돌아야 한다")


if __name__ == "__main__":
    unittest.main()
